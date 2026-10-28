from app.escopo import EscopoCla
from app.models import TarefaPessoal


def do_membro(escopo: EscopoCla, membro_id: int) -> list[TarefaPessoal]:
    """Tarefa pessoal e do dono e de mais ninguem: o filtro por membro nunca sai daqui."""
    stmt = escopo.q(TarefaPessoal).where(
        TarefaPessoal.membro_id == membro_id, TarefaPessoal.excluida_em.is_(None)
    )
    return list(escopo.db.scalars(stmt))


def na_lixeira_do_membro(escopo: EscopoCla, membro_id: int) -> list[TarefaPessoal]:
    stmt = (
        escopo.q(TarefaPessoal)
        .where(TarefaPessoal.excluida_em.is_not(None), TarefaPessoal.membro_id == membro_id)
        .order_by(TarefaPessoal.excluida_em.desc())
    )
    return list(escopo.db.scalars(stmt))


def por_id(escopo: EscopoCla, tarefa_id: int) -> TarefaPessoal | None:
    return escopo.obter(TarefaPessoal, tarefa_id)


def na_coluna(escopo: EscopoCla, coluna_id: int) -> list[TarefaPessoal]:
    stmt = escopo.q(TarefaPessoal).where(TarefaPessoal.coluna_id == coluna_id)
    return list(escopo.db.scalars(stmt))
