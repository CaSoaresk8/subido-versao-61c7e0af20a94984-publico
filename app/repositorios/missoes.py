from sqlalchemy.orm import selectinload

from app.escopo import EscopoCla
from app.models import Missao


def ativas(escopo: EscopoCla, com_entregas: bool = False) -> list[Missao]:
    """Missoes que nao estao na lixeira, as com vencimento mais perto primeiro.

    com_entregas=True carrega as entregas junto, numa consulta so. Quem percorre missao.entregas
    (ranking, grafico, progresso) PRECISA pedir isso: sem o carregamento junto, o SQLAlchemy vai ao
    banco uma vez por missao, e com dezenas de clas isso e a lentidao que se quer evitar.

    Quem nao toca em .entregas nao pede, para nao pagar uma consulta a toa.
    """
    stmt = escopo.q(Missao).where(Missao.excluida_em.is_(None))
    if com_entregas:
        stmt = stmt.options(selectinload(Missao.entregas))
    return list(escopo.db.scalars(stmt.order_by(Missao.vencimento.is_(None), Missao.vencimento)))


def na_lixeira(escopo: EscopoCla) -> list[Missao]:
    stmt = (
        escopo.q(Missao).where(Missao.excluida_em.is_not(None)).order_by(Missao.excluida_em.desc())
    )
    return list(escopo.db.scalars(stmt))


def por_id(escopo: EscopoCla, missao_id: int) -> Missao | None:
    return escopo.obter(Missao, missao_id)
