from sqlalchemy import func, select

from app.escopo import EscopoCla
from app.models import Coluna


def do_membro(escopo: EscopoCla, membro_id: int) -> list[Coluna]:
    stmt = escopo.q(Coluna).where(Coluna.membro_id == membro_id).order_by(Coluna.ordem, Coluna.id)
    return list(escopo.db.scalars(stmt))


def por_id(escopo: EscopoCla, coluna_id: int) -> Coluna | None:
    return escopo.obter(Coluna, coluna_id)


def maior_ordem(escopo: EscopoCla, membro_id: int) -> int:
    stmt = select(func.max(Coluna.ordem)).where(
        Coluna.cla_id == escopo.cla_id, Coluna.membro_id == membro_id
    )
    return escopo.db.scalar(stmt) or 0
