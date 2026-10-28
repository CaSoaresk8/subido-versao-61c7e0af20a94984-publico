from sqlalchemy import func, select

from app.escopo import EscopoCla
from app.models import CONCLUIDO, Entrega, Missao


def _no_mesmo_cla():
    """A condicao de juncao entre entrega e missao, com o cla dentro.

    A FK e composta, entao a juncao tambem e: sem `Entrega.cla_id == Missao.cla_id` o banco pode
    casar a entrega de um cla com a missao de outro que tenha o mesmo id, e ids batem entre clas
    toda hora (cada cla comeca pelo 1). E um erro que passaria: a consulta roda, devolve linha, e
    a linha e de outro cla.
    """
    return (Entrega.missao_id == Missao.id) & (Entrega.cla_id == Missao.cla_id)


def do_membro(escopo: EscopoCla, membro_id: int) -> dict[int, Entrega]:
    """As entregas de uma pessoa, indexadas por missao."""
    stmt = escopo.q(Entrega).where(Entrega.membro_id == membro_id)
    return {entrega.missao_id: entrega for entrega in escopo.db.scalars(stmt)}


def de_missoes_ativas(escopo: EscopoCla) -> list[Entrega]:
    """So as entregas que apontam para missao fora da lixeira.

    Antes isto era select(Entrega) sem filtro nenhum, e a separacao acontecia em Python: o app
    carregava a tabela inteira para descartar a maior parte. O filtro virou JOIN porque e o banco
    que sabe fazer isso com indice, e porque e aqui que o filtro por cla entra.
    """
    stmt = escopo.q(Entrega).join(Missao, _no_mesmo_cla()).where(Missao.excluida_em.is_(None))
    return list(escopo.db.scalars(stmt))


def pontuacao_concluida(escopo: EscopoCla) -> tuple[int, int]:
    """(pontos somados, quantas entregas) das conclusoes em missao ativa, contado pelo banco.

    O coluna_id IS NULL e a traducao em SQL de servicos/missoes.py:conta_como_concluida, e tem que
    continuar sendo: sem ele o dashboard somava ponto de cartao guardado em coluna privada, que o
    ranking da mesma tela nao somava. tests/test_criterio.py compara as duas contra o mesmo banco.
    """
    pontos, quantas = escopo.db.execute(
        select(func.coalesce(func.sum(Missao.pontos), 0), func.count(Entrega.id))
        .select_from(Entrega)
        .join(Missao, _no_mesmo_cla())
        .where(
            Entrega.cla_id == escopo.cla_id,
            Entrega.status == CONCLUIDO,
            Entrega.coluna_id.is_(None),
            Missao.excluida_em.is_(None),
        )
    ).one()
    return int(pontos), int(quantas)


def obter_ou_criar(escopo: EscopoCla, missao_id: int, membro_id: int) -> Entrega:
    entrega = escopo.db.scalar(
        escopo.q(Entrega).where(Entrega.missao_id == missao_id, Entrega.membro_id == membro_id)
    )
    if entrega is None:
        entrega = Entrega(cla_id=escopo.cla_id, missao_id=missao_id, membro_id=membro_id)
        escopo.db.add(entrega)
        escopo.db.flush()
    return entrega


def na_coluna(escopo: EscopoCla, coluna_id: int) -> list[Entrega]:
    return list(escopo.db.scalars(escopo.q(Entrega).where(Entrega.coluna_id == coluna_id)))
