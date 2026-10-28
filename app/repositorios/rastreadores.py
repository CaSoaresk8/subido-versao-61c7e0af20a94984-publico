"""Consultas do rastreador. Recebem `db`, e nao escopo: este papel atravessa clas de proposito.

Declaradas em `tests/test_isolamento.py:SEM_ESCOPO`. Toda funcao daqui que devolve dado de cla
recebe o rastreador e filtra pelos clas que ELE acompanha; o isolamento nao sumiu, mudou de dono:
em vez do cla da sessao, o recorte e a lista de clas escolhida por ele.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CONCLUIDO,
    Acompanhamento,
    Mentoria,
    Cla,
    ConviteRastreador,
    Entrega,
    Log,
    Membro,
    Missao,
    Rastreador,
    RastreadorCla,
    TarefaPessoal,
    Usuario,
    agora,
)


def por_usuario(db: Session, usuario_id: int) -> Rastreador | None:
    """O papel da conta, se ela tiver. Desligado (`ativo=False`) conta como nao ter."""
    return db.scalar(
        select(Rastreador).where(Rastreador.usuario_id == usuario_id, Rastreador.ativo.is_(True))
    )


def todos(db: Session) -> list[Rastreador]:
    return list(db.scalars(select(Rastreador).order_by(Rastreador.criado_em)))


def ids_dos_clas(db: Session, rastreador: Rastreador) -> set[int]:
    return set(
        db.scalars(select(RastreadorCla.cla_id).where(RastreadorCla.rastreador_id == rastreador.id))
    )


def clas_acompanhados(db: Session, rastreador: Rastreador) -> list[Cla]:
    stmt = (
        select(Cla)
        .join(RastreadorCla, RastreadorCla.cla_id == Cla.id)
        .where(RastreadorCla.rastreador_id == rastreador.id)
        .order_by(Cla.nome)
    )
    return list(db.scalars(stmt))


def clas_para_escolher(db: Session) -> list[tuple[Cla, int]]:
    """Todos os clas com quantas pessoas tem, para a tela de escolha.

    So nome e tamanho: escolher um cla nao pode exigir ver o que tem dentro dele antes.
    """
    stmt = (
        select(Cla, func.count(Membro.id))
        .outerjoin(Membro, Membro.cla_id == Cla.id)
        .group_by(Cla.id)
        .order_by(Cla.nome)
    )
    return [(cla, quantos) for cla, quantos in db.execute(stmt)]


def acompanha(db: Session, rastreador: Rastreador, cla_id: int) -> bool:
    return (
        db.scalar(
            select(RastreadorCla.id).where(
                RastreadorCla.rastreador_id == rastreador.id, RastreadorCla.cla_id == cla_id
            )
        )
        is not None
    )


def membro_acompanhado(db: Session, rastreador: Rastreador, membro_id: int) -> Membro | None:
    """Uma pessoa, so se ela estiver num cla que este rastreador acompanha.

    E o `escopo.obter` do rastreador: id de fora da lista dele devolve None, e o router transforma
    em 404. Sem isto, bastaria trocar o numero da URL para ver qualquer pessoa da plataforma.
    """
    stmt = (
        select(Membro)
        .join(RastreadorCla, RastreadorCla.cla_id == Membro.cla_id)
        .where(RastreadorCla.rastreador_id == rastreador.id, Membro.id == membro_id)
    )
    return db.scalar(stmt)


def pessoas(db: Session, rastreador: Rastreador) -> list[dict]:
    """A lista do painel: uma linha por pessoa dos clas acompanhados.

    Uma consulta por metrica, e nao uma por pessoa: com dezenas de clas, o segundo formato vira
    centenas de idas ao banco para desenhar uma tela.
    """
    clas = ids_dos_clas(db, rastreador)
    if not clas:
        return []

    membros = list(db.scalars(select(Membro).where(Membro.cla_id.in_(clas)).order_by(Membro.nome)))
    nomes_de_cla = {
        cla_id: nome
        for cla_id, nome in db.execute(select(Cla.id, Cla.nome).where(Cla.id.in_(clas)))
    }
    total_de_missoes = dict(
        db.execute(
            select(Missao.cla_id, func.count(Missao.id))
            .where(Missao.cla_id.in_(clas), Missao.excluida_em.is_(None))
            .group_by(Missao.cla_id)
        ).all()
    )
    concluidas = dict(
        db.execute(
            select(Entrega.membro_id, func.count(Entrega.id))
            .join(Missao, (Missao.id == Entrega.missao_id) & (Missao.cla_id == Entrega.cla_id))
            .where(
                Entrega.cla_id.in_(clas),
                Entrega.status == CONCLUIDO,
                Entrega.coluna_id.is_(None),
                Missao.excluida_em.is_(None),
            )
            .group_by(Entrega.membro_id)
        ).all()
    )
    pontos = dict(
        db.execute(
            select(Entrega.membro_id, func.sum(Missao.pontos))
            .join(Missao, (Missao.id == Entrega.missao_id) & (Missao.cla_id == Entrega.cla_id))
            .where(
                Entrega.cla_id.in_(clas),
                Entrega.status == CONCLUIDO,
                Entrega.coluna_id.is_(None),
                Missao.excluida_em.is_(None),
            )
            .group_by(Entrega.membro_id)
        ).all()
    )
    ultima_entrega = dict(
        db.execute(
            select(Entrega.membro_id, func.max(Entrega.atualizada_em))
            .where(Entrega.cla_id.in_(clas))
            .group_by(Entrega.membro_id)
        ).all()
    )
    ultima_tarefa = dict(
        db.execute(
            select(TarefaPessoal.membro_id, func.max(TarefaPessoal.criada_em))
            .where(TarefaPessoal.cla_id.in_(clas))
            .group_by(TarefaPessoal.membro_id)
        ).all()
    )

    linhas = []
    for membro in membros:
        marcas = [
            membro.entrou_em,
            ultima_entrega.get(membro.id),
            ultima_tarefa.get(membro.id),
        ]
        ultima = max([m for m in marcas if m is not None])
        total = total_de_missoes.get(membro.cla_id, 0)
        feitas = concluidas.get(membro.id, 0)
        linhas.append(
            {
                "membro": membro,
                "cla_nome": nomes_de_cla.get(membro.cla_id, ""),
                "concluidas": feitas,
                "pendentes": max(0, total - feitas),
                "pontos": int(pontos.get(membro.id) or 0),
                "ultima_atividade": ultima,
                "dias_parado": (agora() - ultima).days,
            }
        )
    # Quem esta parado ha mais tempo primeiro: o painel existe para achar quem sumiu, e nao para
    # admirar quem ja esta em dia.
    linhas.sort(key=lambda linha: (-linha["dias_parado"], linha["membro"].nome))
    return linhas


def email_do_membro(db: Session, membro: Membro) -> str:
    """O email de contato de uma pessoa acompanhada. So a ficha individual mostra."""
    return db.scalar(select(Usuario.email).where(Usuario.id == membro.usuario_id)) or ""


def convite_por_token(db: Session, token: str) -> ConviteRastreador | None:
    return db.scalar(select(ConviteRastreador).where(ConviteRastreador.token == token))


def convites(db: Session) -> list[ConviteRastreador]:
    return list(db.scalars(select(ConviteRastreador).order_by(ConviteRastreador.criado_em.desc())))


def vale(convite: ConviteRastreador | None, quando: datetime | None = None) -> bool:
    quando = quando or agora()
    if convite is None or convite.revogado_em is not None or convite.expira_em < quando:
        return False
    return convite.max_usos is None or convite.usos < convite.max_usos


def tarefas_da_mentoria(db: Session, membro: Membro) -> list[TarefaPessoal]:
    """So as tarefas que a mentoria criou para esta pessoa. As pessoais nao saem daqui."""
    stmt = (
        select(TarefaPessoal)
        .where(
            TarefaPessoal.cla_id == membro.cla_id,
            TarefaPessoal.membro_id == membro.id,
            TarefaPessoal.criada_por_rastreador_id.is_not(None),
            TarefaPessoal.excluida_em.is_(None),
        )
        .order_by(TarefaPessoal.prazo.is_(None), TarefaPessoal.prazo, TarefaPessoal.criada_em)
    )
    return list(db.scalars(stmt))


def mentorias_da_pessoa(db: Session, membro: Membro) -> list[Mentoria]:
    """Todas as consultorias da pessoa, da mais recente para a mais antiga."""
    stmt = (
        select(Mentoria)
        .where(Mentoria.cla_id == membro.cla_id, Mentoria.membro_id == membro.id)
        .order_by(Mentoria.inicio.desc())
    )
    return list(db.scalars(stmt))


def acompanhamento_da_pessoa(db: Session, membro: Membro) -> Acompanhamento | None:
    return db.scalar(
        select(Acompanhamento).where(
            Acompanhamento.cla_id == membro.cla_id, Acompanhamento.membro_id == membro.id
        )
    )


def nomes_de_rastreadores(db: Session, ids: set[int]) -> dict[int, str]:
    """id do rastreador -> nome da pessoa, para o cartao dizer quem da mentoria criou a tarefa."""
    if not ids:
        return {}
    stmt = (
        select(Rastreador.id, Usuario.nome)
        .join(Usuario, Usuario.id == Rastreador.usuario_id)
        .where(Rastreador.id.in_(ids))
    )
    return dict(db.execute(stmt).all())


def historico_do_saldo(db: Session, membro: Membro) -> list[Log]:
    """Todo ajuste do saldo desta pessoa, de quem quer que tenha feito, do mais recente para tras.

    Existe porque a propria pessoa pode mexer no saldo. O rastreador precisa ver isso sem ter que
    perguntar: e a unica defesa de um limite que deixou de ser trava.
    """
    registro = acompanhamento_da_pessoa(db, membro)
    if registro is None:
        return []
    stmt = (
        select(Log)
        .where(
            Log.cla_id == membro.cla_id,
            Log.entidade == "acompanhamento",
            Log.entidade_id == registro.id,
        )
        .order_by(Log.criado_em.desc())
    )
    return list(db.scalars(stmt))
