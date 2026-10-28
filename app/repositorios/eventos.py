from datetime import datetime

from sqlalchemy import select

from app.escopo import EscopoCla
from app.models import Evento, Membro, Usuario


def ativos(escopo: EscopoCla) -> list[Evento]:
    """Todos os eventos fora da lixeira, do mais cedo para o mais tarde."""
    stmt = escopo.q(Evento).where(Evento.excluido_em.is_(None)).order_by(Evento.inicio)
    return list(escopo.db.scalars(stmt))


def futuros(escopo: EscopoCla, a_partir_de: datetime) -> list[Evento]:
    """Os que ainda nao comecaram. E a lista que recebe quem entra no cla depois do convite."""
    stmt = (
        escopo.q(Evento)
        .where(Evento.excluido_em.is_(None), Evento.inicio >= a_partir_de)
        .order_by(Evento.inicio)
    )
    return list(escopo.db.scalars(stmt))


def do_periodo(escopo: EscopoCla, de: datetime, ate: datetime) -> list[Evento]:
    """Para o calendario do painel: so o mes que esta na tela, e nao a agenda inteira."""
    stmt = (
        escopo.q(Evento)
        .where(Evento.excluido_em.is_(None), Evento.inicio >= de, Evento.inicio < ate)
        .order_by(Evento.inicio)
    )
    return list(escopo.db.scalars(stmt))


def na_lixeira(escopo: EscopoCla) -> list[Evento]:
    stmt = (
        escopo.q(Evento).where(Evento.excluido_em.is_not(None)).order_by(Evento.excluido_em.desc())
    )
    return list(escopo.db.scalars(stmt))


def por_id(escopo: EscopoCla, evento_id: int) -> Evento | None:
    return escopo.obter(Evento, evento_id)


def emails_dos_membros(escopo: EscopoCla) -> list[str]:
    """O email de cadastro de cada membro do cla, que e para onde o convite vai.

    Email e dado pessoal e mora em `usuario`, nao em `membro`: por isso o join, e por isso esta
    funcao so e chamada por quem monta o convite. Nenhuma tela lista isto.
    """
    stmt = (
        select(Usuario.email)
        .join(Membro, Membro.usuario_id == Usuario.id)
        .where(Membro.cla_id == escopo.cla_id)
        .order_by(Usuario.email)
    )
    return list(escopo.db.scalars(stmt))
