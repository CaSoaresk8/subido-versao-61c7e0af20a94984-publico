from sqlalchemy.orm import joinedload

from app.escopo import EscopoCla
from app.models import Convite


def do_cla(escopo: EscopoCla) -> list[Convite]:
    """Os convites do cla ativo, o mais novo primeiro.

    Quem gerou aparece na tela, entao vem carregado junto: sem isso seria uma consulta por convite
    so para escrever o nome de quem criou.
    """
    stmt = (
        escopo.q(Convite).options(joinedload(Convite.criado_por)).order_by(Convite.criado_em.desc())
    )
    return list(escopo.db.scalars(stmt))


def por_id(escopo: EscopoCla, convite_id: int) -> Convite | None:
    return escopo.obter(Convite, convite_id)
