"""Consultas que sao da plataforma, e nao de um cla. Por isso recebem `db`, e nao escopo.

Estao declaradas em `tests/test_isolamento.py:SEM_ESCOPO`, e cada uma diz ali por que pode rodar
fora de cla. Nenhuma devolve dado de cla para uma tela: sao usadas por quem monta os convites.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Evento, IntegracaoGoogle


def integracao_google(db: Session) -> IntegracaoGoogle | None:
    """A conta que manda os convites de todos os clas. No maximo uma linha."""
    return db.scalar(select(IntegracaoGoogle).order_by(IntegracaoGoogle.id.desc()).limit(1))


def futuros_de_todos_os_clas(db: Session, a_partir_de: datetime) -> list[Evento]:
    """Para quando a conta e conectada: o que ja estava marcado, em todo cla, vira convite.

    Cada evento sai daqui e e sincronizado com o escopo do PROPRIO cla (ver
    `servicos/agenda.sincronizar_todos`), entao os convidados de cada um sao os membros dele.
    """
    stmt = (
        select(Evento)
        .where(Evento.excluido_em.is_(None), Evento.inicio >= a_partir_de)
        .order_by(Evento.cla_id, Evento.inicio)
    )
    return list(db.scalars(stmt))
