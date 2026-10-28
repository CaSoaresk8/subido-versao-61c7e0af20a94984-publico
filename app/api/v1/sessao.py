"""Entrar, sair, saber quem esta logado e trocar de cla ativo.

O estado da sessao e uma coisa so, e por isso as quatro rotas devolvem o mesmo objeto: a conta, a
participacao no cla que esta ativo, o cla, e a lista de clas de que a pessoa participa. Quem acabou
de entrar e quem acabou de trocar de cla precisam exatamente da mesma informacao que quem so abriu
o app, e devolver formatos diferentes obrigaria a tela a ter tres caminhos para chegar no mesmo
lugar.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import saida
from app.api.deps import escopo_api, exige_origem_propria
from app.database import get_db
from app.deps import abrir_sessao
from app.escopo import EscopoCla
from app.repositorios import contas as repo_contas
from app.security import conferir_senha

router = APIRouter(tags=["sessao"])


class Credenciais(BaseModel):
    email: str
    senha: str


class ClaEscolhido(BaseModel):
    cla_id: int


def estado(escopo: EscopoCla) -> dict:
    """O retrato da sessao. Usado tambem por quem cria cla e por quem entra por convite.

    `clas` sai daqui em toda resposta de sessao porque o seletor do cabecalho depende dela e ela
    muda justamente nos momentos em que esta funcao e chamada: entrar, criar um cla, aceitar um
    convite. Pedir a lista numa rota separada faria o seletor aparecer desatualizado exatamente
    depois da acao que o mudou.
    """
    participacoes = repo_contas.membros_do_usuario(escopo.db, escopo.membro.usuario_id)
    return {
        "usuario": saida.usuario(escopo.membro.usuario),
        "membro": saida.membro(escopo.membro),
        "cla": saida.cla(escopo.cla),
        "clas": [saida.cla(participacao.cla) for participacao in participacoes],
    }


@router.get("/sessao")
def ver(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    return estado(escopo)


@router.post("/sessao", dependencies=[Depends(exige_origem_propria)])
def entrar(
    request: Request,
    credenciais: Credenciais,
    db: Session = Depends(get_db),
) -> dict:
    """Confere a senha contra `Usuario` e abre a sessao no primeiro cla da pessoa.

    Conta que nao existe e senha errada dao a MESMA resposta, com a mesma mensagem e o mesmo 401.
    Dizer "esse email nao esta cadastrado" e confirmar quem tem conta aqui para quem estiver
    testando uma lista de emails.

    Conta sem cla nenhum e outro caso, e sai com 403 e `codigo` proprio: a senha estava certa, o que
    falta e destino, e a tela precisa poder mandar a pessoa para criar um cla em vez de mostrar
    "senha incorreta" para quem acertou a senha.
    """
    usuario = repo_contas.usuario_por_email(db, credenciais.email)
    if usuario is None or not conferir_senha(credenciais.senha, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="Email ou senha incorretos.")

    participacoes = repo_contas.membros_do_usuario(db, usuario.id)
    if not participacoes:
        raise HTTPException(
            status_code=403,
            detail={
                "codigo": "sem_cla",
                "mensagem": (
                    "Sua conta não está em nenhum clã. Use o link de convite de quem te chamou, "
                    "ou crie um clã novo."
                ),
            },
        )

    abrir_sessao(request, participacoes[0])
    return estado(EscopoCla(db=db, membro=participacoes[0]))


@router.delete("/sessao", status_code=204, dependencies=[Depends(exige_origem_propria)])
def sair(request: Request) -> Response:
    """Sair nao exige estar dentro: quem manda isto com a sessao ja vencida recebe o mesmo 204.

    Devolver 401 para quem pede para sair seria pedir que a pessoa entre para poder sair, e a tela
    faz este pedido justamente quando desconfia que a sessao acabou.
    """
    request.session.clear()
    return Response(status_code=204)


@router.put("/sessao/cla", dependencies=[Depends(exige_origem_propria)])
def trocar_cla(
    request: Request,
    escolha: ClaEscolhido,
    escopo: EscopoCla = Depends(escopo_api),
) -> dict:
    """Troca o cla que a sessao esta olhando. O cla anterior continua existindo e editavel.

    A participacao e reconferida no banco antes de a sessao mudar. Sem isso este pedido seria um
    jeito de entrar em qualquer cla escrevendo o id na mao, e o cookie passaria a valer como
    autorizacao. Cla do qual a pessoa nao participa da 404, igual a cla que nao existe.
    """
    destino = repo_contas.membro_do_usuario_no_cla(
        escopo.db, escopo.membro.usuario_id, escolha.cla_id
    )
    if destino is None:
        raise HTTPException(status_code=404, detail="Clã não encontrado")
    abrir_sessao(request, destino)
    return estado(EscopoCla(db=escopo.db, membro=destino))
