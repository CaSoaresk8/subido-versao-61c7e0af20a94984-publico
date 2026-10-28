"""A missao do cla e a entrega de quem esta logado.

Todas as escritas chamam `servicos/missoes.py`, que e o mesmo que `routers/missoes.py` chama. O que
muda aqui e so a forma da resposta: onde a tela redesenha o HTML com a mensagem, esta camada devolve
um codigo e um JSON. O dia em que a regra mudar, muda num arquivo, e as duas interfaces mudam junto.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api import saida
from app.api.deps import escopo_api, exige_origem_propria
from app.escopo import EscopoCla
from app.models import CONCLUIDO, Missao
from app.repositorios import entregas as repo_entregas
from app.repositorios import membros as repo_membros
from app.repositorios import missoes as repo_missoes
from app.servicos import missoes as servico_missoes
from app.servicos.erros import FaltaResposta
from app.servicos.ranking import progresso_da_missao

router = APIRouter(tags=["missoes"])


class MissaoEnviada(BaseModel):
    titulo: str
    descricao: str = ""
    pontos: int = 0
    vencimento: date | None = None
    exige_resposta: bool = False
    rotulo_resposta: str = ""


class EntregaEnviada(BaseModel):
    status: str
    resposta: str = ""
    observacao: str = ""


def missao_ativa(escopo: EscopoCla, missao_id: int) -> Missao:
    """A missao do cla de quem esta olhando, fora da lixeira, ou 404.

    Missao de outro cla cai no mesmo 404 de missao que nao existe: o repositorio devolve None
    porque a consulta nasce filtrada pelo cla. Um 403 aqui diria "existe, mas nao e do seu cla",
    e isso e exatamente o que alguem varrendo ids quer saber.
    """
    missao = repo_missoes.por_id(escopo, missao_id)
    if missao is None or not missao.ativa:
        raise HTTPException(status_code=404, detail="Missão não encontrada")
    return missao


@router.get("/missoes")
def listar(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """As missoes ativas do cla, cada uma com o progresso e a MINHA entrega.

    A entrega de quem pediu vai junto porque a lista a mostra em toda missao (e o selo de "ja fiz"),
    e busca-la depois seria um pedido por missao. As entregas dos OUTROS nao vao: elas so aparecem
    na tela de uma missao, e mandar todas aqui seria carregar o cla inteiro para desenhar uma lista.
    """
    missoes = repo_missoes.ativas(escopo, com_entregas=True)
    total_membros = repo_membros.total(escopo)
    minhas = repo_entregas.do_membro(escopo, escopo.membro_id)
    hoje = date.today()
    return {
        "missoes": [
            {
                "missao": saida.missao(m),
                "progresso": progresso_da_missao(m, total_membros),
                "minha_entrega": saida.entrega(minhas.get(m.id)),
                "dias": (m.vencimento - hoje).days if m.vencimento else None,
            }
            for m in missoes
        ]
    }


@router.post("/missoes", status_code=201, dependencies=[Depends(exige_origem_propria)])
def criar(pedido: MissaoEnviada, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    missao = servico_missoes.criar(
        escopo,
        titulo=pedido.titulo,
        descricao=pedido.descricao,
        pontos=pedido.pontos,
        vencimento=pedido.vencimento,
        exige_resposta=pedido.exige_resposta,
        rotulo_resposta=pedido.rotulo_resposta,
    )
    escopo.db.commit()
    return saida.missao(missao)


@router.get("/missoes/{missao_id}")
def detalhe(missao_id: int, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """A missao com as entregas de todo mundo, na mesma ordem da tela: quem fez primeiro.

    `rotulo_resposta` sai daqui ja resolvido para o texto padrao quando a missao nao escolheu um.
    O default e regra da missao, nao enfeite de tela, e repeti-lo no React seria uma segunda copia
    de "Link ou texto da entrega" para desandar.
    """
    missao = missao_ativa(escopo, missao_id)
    minha = next((e for e in missao.entregas if e.membro_id == escopo.membro_id), None)
    entregas = sorted(missao.entregas, key=lambda e: (e.status != CONCLUIDO, e.membro.nome))
    return {
        "missao": saida.missao(missao),
        "minha_entrega": saida.entrega(minha),
        "entregas": [saida.entrega(e, com_membro=True) for e in entregas],
        "progresso": progresso_da_missao(missao, repo_membros.total(escopo)),
        "rotulo_resposta": servico_missoes.rotulo_da_resposta(missao),
    }


@router.put("/missoes/{missao_id}", dependencies=[Depends(exige_origem_propria)])
def editar(missao_id: int, pedido: MissaoEnviada, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """Qualquer membro edita qualquer missao do cla. O cla foi pedido sem lider."""
    missao = missao_ativa(escopo, missao_id)
    servico_missoes.editar(
        escopo,
        missao,
        titulo=pedido.titulo,
        descricao=pedido.descricao,
        pontos=pedido.pontos,
        vencimento=pedido.vencimento,
        exige_resposta=pedido.exige_resposta,
        rotulo_resposta=pedido.rotulo_resposta,
    )
    escopo.db.commit()
    return saida.missao(missao)


@router.delete("/missoes/{missao_id}", dependencies=[Depends(exige_origem_propria)])
def excluir(missao_id: int, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """Manda para a lixeira. DELETE, mas a linha fica e da para restaurar pelo historico.

    Devolve a missao marcada em vez de 204 porque `excluida_em` mudou e a tela de historico mostra
    essa data. O verbo e DELETE porque e o que o pedido quer dizer; o que o app faz com ele e outra
    coisa, e esta escrita em `servicos/missoes.py:marcar_excluido`.
    """
    missao = missao_ativa(escopo, missao_id)
    servico_missoes.excluir(escopo, missao)
    escopo.db.commit()
    return saida.missao(missao)


@router.put("/missoes/{missao_id}/entrega", dependencies=[Depends(exige_origem_propria)])
def salvar_entrega(
    missao_id: int, pedido: EntregaEnviada, escopo: EscopoCla = Depends(escopo_api)
) -> dict:
    """Salva a entrega de quem esta logado. Nao da para mexer na entrega de outra pessoa.

    Nao ha `membro_id` no caminho nem no corpo de proposito: a entrega e sempre a de quem pediu, e
    e o escopo que diz quem e. Um id no pedido seria um campo a conferir toda vez, e a primeira vez
    que alguem esquecesse de conferir seria a vez em que daria para concluir a missao no lugar dos
    outros.

    Concluir sem a resposta exigida da 409, e nao 400: o pedido esta correto, o que falta e um passo
    anterior. O corpo carrega `codigo` para a tela poder abrir o campo de resposta em vez de so
    mostrar um alerta.
    """
    missao = missao_ativa(escopo, missao_id)
    try:
        entrega = servico_missoes.salvar_entrega(
            escopo, missao, pedido.status, pedido.resposta, pedido.observacao
        )
    except FaltaResposta as recusa:
        # O servico ja escreveu na entrega antes de descobrir que o campo estava vazio. Sem o
        # rollback, a resposta em branco ficaria gravada junto com o status antigo.
        escopo.db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "falta_resposta",
                "mensagem": servico_missoes.frase_de_falta_de_resposta(missao),
                "missao_id": missao.id,
                "rotulo_resposta": servico_missoes.rotulo_da_resposta(missao),
            },
        ) from recusa
    escopo.db.commit()
    return saida.entrega(entrega)
