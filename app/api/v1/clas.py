"""Criar cla e trocar o logo do cla ativo.

Aqui a API se afasta de proposito do formulario de `/criar-cla`, e e o unico lugar da fase 4 onde
isso acontece. A tela em HTML cria conta, cla e logo num envio so porque um formulario tem um botao
de enviar, e por causa disso ela e obrigada a conferir a imagem ANTES de escrever qualquer coisa:
sem essa ordem, um PNG torto deixaria meio cla no banco para depois ser desfeito.

O JSON nao tem essa amarra. Criar o cla e por o logo sao dois pedidos, e a razao da ordem estrita
some junto: quando o logo chega, o cla ja existe, e um arquivo recusado nao deixa nada pela metade.
O que nao muda e a regra, que continua morando em `servicos/contas.py` e `servicos/logos.py`.
"""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import saida
from app.api.deps import escopo_api, exige_origem_propria
from app.api.v1.sessao import estado
from app.database import get_db
from app.deps import abrir_sessao, escopo_opcional
from app.escopo import EscopoCla
from app.repositorios import contas as repo_contas
from app.servicos import contas as servico_contas
from app.servicos import logos as servico_logos

router = APIRouter(tags=["clas"])


class ContaNova(BaseModel):
    """Os mesmos quatro campos do `_campos_conta.html`, e nao por simetria de fachada.

    A regra que julga os quatro e uma so, em `servicos/contas.py`. Se aqui faltasse o telefone, a
    API seria uma porta que cria conta sem o que a tela exige, e a diferenca so apareceria no dia em
    que alguem precisasse falar com essa pessoa.
    """

    nome: str
    email: str
    senha: str
    telefone: str


class ClaNovo(BaseModel):
    """`conta` so vem de quem ainda nao tem sessao. Quem ja esta logado abre o cla com a conta dela.

    Sao os dois estados da mesma porta, e e por isso que sao um campo opcional e nao duas rotas:
    quem chega de fora manda a conta junto, quem ja esta dentro manda so o nome do cla.
    """

    nome: str
    conta: ContaNova | None = None


def usuario_do_pedido(db: Session, escopo: EscopoCla | None, conta: ContaNova | None):
    """A conta que vai abrir o cla: a da sessao, ou uma nova criada agora. Nao da commit."""
    if escopo is not None:
        usuario = repo_contas.usuario_por_id(db, escopo.membro.usuario_id)
        if usuario is None:
            # Sessao apontando para conta que nao existe mais. Nao da para criar cla para ninguem.
            raise HTTPException(status_code=401, detail="Conta não encontrada.")
        return usuario

    if conta is None:
        raise HTTPException(
            status_code=422, detail="Mande os dados da conta ou entre antes de criar o clã."
        )
    problema = servico_contas.validar(
        db, conta.nome.strip(), conta.email.strip(), conta.senha, conta.telefone
    )
    if problema:
        raise HTTPException(status_code=400, detail=problema)
    return servico_contas.criar_usuario(db, conta.nome, conta.email, conta.senha, conta.telefone)


@router.get("/clas")
def listar(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """Os clas de quem esta logado. A mesma lista que `GET /sessao` devolve em `clas`.

    Existe separada porque o seletor de cla precisa dela sozinha depois de entrar num cla novo, e
    pedir a sessao inteira so para atualizar um menu traz junto o estado que nao mudou.
    """
    participacoes = repo_contas.membros_do_usuario(escopo.db, escopo.membro.usuario_id)
    return {"clas": [saida.cla(p.cla) for p in participacoes]}


@router.post("/clas", status_code=201, dependencies=[Depends(exige_origem_propria)])
def criar(
    request: Request,
    pedido: ClaNovo,
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
) -> dict:
    """Abre um cla e ja deixa a sessao olhando para ele. Devolve o estado inteiro da sessao.

    Devolve o estado e nao so o cla porque quem cria um cla muda de cla ativo no mesmo movimento:
    a participacao e outra, a lista de clas cresceu, e a tela precisa das tres coisas juntas.
    """
    problema = servico_contas.validar_nome_de_cla(pedido.nome)
    if problema:
        raise HTTPException(status_code=400, detail=problema)

    usuario = usuario_do_pedido(db, escopo, pedido.conta)
    membro = servico_contas.criar_cla(db, usuario, pedido.nome)
    db.commit()
    abrir_sessao(request, membro)
    return estado(EscopoCla(db=db, membro=membro))


@router.put("/clas/atual/logo", dependencies=[Depends(exige_origem_propria)])
def trocar_logo(
    arquivo: UploadFile = File(...),
    escopo: EscopoCla = Depends(escopo_api),
) -> dict:
    """Poe ou troca o logo do cla ativo. Qualquer membro pode, como tudo mais no cla.

    `conferir` decodifica o arquivo de verdade antes de gravar: o motivo esta escrito em
    `servicos/logos.py`, e vale igual para esta rota e para a tela.
    """
    try:
        imagem = servico_logos.conferir(arquivo.file.read())
    except servico_logos.LogoInvalido as recusa:
        raise HTTPException(status_code=400, detail=str(recusa)) from recusa

    cla = escopo.cla
    cla.logo = servico_logos.gravar(imagem, cla.id, anterior=cla.logo)
    escopo.db.commit()
    return saida.cla(cla)


@router.delete("/clas/atual/logo", dependencies=[Depends(exige_origem_propria)])
def tirar_logo(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """Tira o logo e volta ao icone do app. Cla que ja estava sem logo recebe a mesma resposta.

    Nao e 404: o pedido e "este cla nao tem logo", e o estado final e esse nos dois casos. Dois
    cliques em duas abas nao podem dar respostas diferentes.
    """
    cla = escopo.cla
    if cla.logo:
        servico_logos.apagar(cla.logo)
        cla.logo = None
        escopo.db.commit()
    return saida.cla(cla)
