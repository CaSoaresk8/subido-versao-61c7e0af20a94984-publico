"""O convite dos dois lados: quem gera de dentro do cla e quem chega de fora com o token.

As rotas de dentro (`/convites`) exigem sessao, como qualquer coisa do cla. As de fora
(`/convite/{token}`) nao exigem nada, e nao poderiam: elas existem justamente para quem ainda nao
tem conta. O que separa uma coisa da outra e o token, e quem decide se ele vale e
`servicos/convites.py`, sempre. Nenhuma das quatro condicoes de validade e reconferida aqui.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import saida
from app.api.deps import escopo_api, exige_origem_propria
from app.api.v1.clas import ContaNova, usuario_do_pedido
from app.api.v1.sessao import estado
from app.database import get_db
from app.deps import abrir_sessao, escopo_opcional
from app.escopo import EscopoCla
from app.repositorios import contas as repo_contas
from app.repositorios import convites as repo_convites
from app.servicos import contas as servico_contas
from app.servicos import convites as servico_convites

router = APIRouter(tags=["convites"])


class ConviteNovo(BaseModel):
    dias: int = servico_convites.VALIDADE_PADRAO
    # Vazio e "sem limite de usos", que e o caso comum: um link so para chamar o cla inteiro.
    max_usos: int | None = None


class EntradaPorConvite(BaseModel):
    conta: ContaNova | None = None


def link_base(request: Request) -> str:
    """De onde o link de convite sai, para quem convida poder copiar e colar em qualquer lugar.

    Vem do pedido e nao de configuracao: o app responde em cla.ialabor.com em producao e em
    localhost no dev, e um endereco fixo no config daria link que nao abre no dev.
    """
    return str(request.base_url).rstrip("/")


@router.get("/convites")
def listar(request: Request, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    registros = repo_convites.do_cla(escopo)
    return {
        "convites": [saida.convite(c, link_base(request)) for c in registros],
        "validades": list(servico_convites.VALIDADES),
        "validade_padrao": servico_convites.VALIDADE_PADRAO,
        "maximo_de_usos": servico_convites.MAXIMO_DE_USOS,
    }


@router.post("/convites", status_code=201, dependencies=[Depends(exige_origem_propria)])
def gerar(
    request: Request,
    pedido: ConviteNovo,
    escopo: EscopoCla = Depends(escopo_api),
) -> dict:
    problema = servico_convites.validar_pedido(pedido.dias, pedido.max_usos)
    if problema:
        raise HTTPException(status_code=400, detail=problema)
    convite = servico_convites.gerar(escopo, dias=pedido.dias, max_usos=pedido.max_usos)
    escopo.db.commit()
    return saida.convite(convite, link_base(request))


@router.delete("/convites/{convite_id}", dependencies=[Depends(exige_origem_propria)])
def revogar(
    convite_id: int,
    request: Request,
    escopo: EscopoCla = Depends(escopo_api),
) -> dict:
    """Mata o link. DELETE, mas a linha fica: o historico de quem convidou quem tem que continuar.

    Para quem tem o link na mao, revogar e apagar, e e por isso que o verbo e DELETE. Devolve o
    convite atualizado em vez de 204 porque ele continua na lista da tela, agora com `situacao`
    "revogado", e a tela precisa do registro para redesenhar a linha sem pedir tudo de novo.
    """
    convite = repo_convites.por_id(escopo, convite_id)
    if convite is None:
        # Convite de outro cla e convite que nao existe dao o mesmo 404. Um 403 aqui confirmaria
        # que o id existe em algum lugar, que e exatamente o que nao se quer contar.
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    servico_convites.revogar(escopo, convite)
    escopo.db.commit()
    return saida.convite(convite, link_base(request))


@router.get("/convite/{token}")
def ver(
    token: str,
    resposta: Response,
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
) -> dict:
    """O que a tela de convite precisa saber antes de alguem clicar em entrar. Rota publica.

    O nome do cla aparece quando o convite vale, e nao aparece quando ele nao vale. Nao e descuido:
    quem tem um token valido na mao ja foi autorizado a entrar e precisa saber onde esta entrando;
    quem chegou com um token vencido ou inventado nao recebe nome de cla nenhum.

    Token inexistente da 404 e token que existe mas nao serve mais da 400, com mensagens diferentes.
    Aqui nao ha o que esconder, ao contrario do 404 de id alheio: um convite invalido nao conta nada
    sobre o cla, e quem chegou com um link quebrado precisa saber se pede outro ou se errou o
    endereco.
    """
    convite, recusa = servico_convites.abrir(db, token)
    destino = repo_contas.cla_por_id(db, convite.cla_id) if convite and not recusa else None
    if recusa:
        resposta.status_code = 404 if convite is None else 400
    ja_membro = (
        escopo is not None
        and convite is not None
        and repo_contas.membro_do_usuario_no_cla(db, escopo.membro.usuario_id, convite.cla_id)
        is not None
    )
    return {
        "token": token,
        "cla": saida.cla(destino) if destino else None,
        "recusa": recusa,
        "ja_membro": ja_membro,
        "logado": escopo is not None,
    }


@router.post("/convite/{token}", dependencies=[Depends(exige_origem_propria)])
def entrar(
    request: Request,
    token: str,
    pedido: EntradaPorConvite,
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
) -> dict:
    """Entra no cla do token e ja deixa a sessao olhando para ele. Rota publica.

    A validade e conferida AQUI, e nao so no GET: entre abrir a tela e mandar este pedido o convite
    pode ter sido revogado, vencido ou esgotado por outra pessoa. Conferir so na leitura deixaria a
    recusa valendo enquanto a aba estivesse aberta.
    """
    convite, recusa = servico_convites.abrir(db, token)
    if recusa:
        raise HTTPException(status_code=404 if convite is None else 400, detail=recusa)

    cla = repo_contas.cla_por_id(db, convite.cla_id)
    if cla is None:
        raise HTTPException(status_code=404, detail="Clã não encontrado")

    usuario = usuario_do_pedido(db, escopo, pedido.conta)
    ja_era = repo_contas.membro_do_usuario_no_cla(db, usuario.id, cla.id) is not None
    membro = servico_contas.entrar_no_cla(db, usuario, cla)
    # Quem ja estava dentro nao gasta uso do convite. Um link reaberto por quem ja e membro nao e
    # entrada nova, e contar como uso esgotaria o convite dos outros sem ninguem ter entrado.
    if not ja_era:
        servico_convites.consumir(EscopoCla(db=db, membro=membro), convite)
    db.commit()

    abrir_sessao(request, membro)
    return estado(EscopoCla(db=db, membro=membro))
