from app.escopo import EscopoCla
from app.models import Membro


def todos(escopo: EscopoCla) -> list[Membro]:
    return list(escopo.db.scalars(escopo.q(Membro).order_by(Membro.nome)))


def total(escopo: EscopoCla) -> int:
    """Quantas pessoas estao no cla. Era tirado de numeros_do_cla(), que calcula o dashboard
    inteiro so para devolver esse numero."""
    return escopo.contar(Membro)


def nomes(escopo: EscopoCla) -> dict[int, str]:
    return {membro.id: membro.nome for membro in escopo.db.scalars(escopo.q(Membro))}


def por_id(escopo: EscopoCla, membro_id: int) -> Membro | None:
    return escopo.obter(Membro, membro_id)
