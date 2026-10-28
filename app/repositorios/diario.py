"""Consultas do acompanhamento semanal. Todas escopadas pelo cla, como o resto dos repositorios."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.escopo import EscopoCla
from app.models import DiarioEntrada, PerfilMembro, ResponsavelSemana


def responsavel_da_semana(escopo: EscopoCla, semana: date) -> ResponsavelSemana | None:
    return escopo.db.scalar(escopo.q(ResponsavelSemana).where(ResponsavelSemana.semana == semana))


def entradas_da_semana(escopo: EscopoCla, semana: date) -> dict[int, DiarioEntrada]:
    """membro_id -> a conversa daquela semana. E o que diz quem ja foi conversado e quem falta."""
    stmt = escopo.q(DiarioEntrada).where(DiarioEntrada.semana == semana)
    return {e.membro_id: e for e in escopo.db.scalars(stmt)}


def ultimas_entradas(escopo: EscopoCla) -> dict[int, DiarioEntrada]:
    """membro_id -> a conversa mais recente da pessoa, de qualquer semana.

    O cartao mostra o status ATUAL, e numa segunda-feira de manha ninguem conversou ainda: sem isto
    o cla inteiro apareceria sem status no comeco de toda semana.
    """
    ultima = (
        select(DiarioEntrada.membro_id, func.max(DiarioEntrada.semana).label("semana"))
        .where(DiarioEntrada.cla_id == escopo.cla_id)
        .group_by(DiarioEntrada.membro_id)
        .subquery()
    )
    stmt = escopo.q(DiarioEntrada).join(
        ultima,
        (ultima.c.membro_id == DiarioEntrada.membro_id) & (ultima.c.semana == DiarioEntrada.semana),
    )
    return {e.membro_id: e for e in escopo.db.scalars(stmt)}


def historico_da_pessoa(escopo: EscopoCla, membro_id: int) -> list[DiarioEntrada]:
    stmt = (
        escopo.q(DiarioEntrada)
        .where(DiarioEntrada.membro_id == membro_id)
        .order_by(DiarioEntrada.semana.desc())
    )
    return list(escopo.db.scalars(stmt))


def perfil(escopo: EscopoCla, membro_id: int) -> PerfilMembro | None:
    return escopo.db.scalar(escopo.q(PerfilMembro).where(PerfilMembro.membro_id == membro_id))
