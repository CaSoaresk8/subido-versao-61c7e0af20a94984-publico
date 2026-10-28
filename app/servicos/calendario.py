import calendar
from collections import defaultdict
from datetime import date

from app.escopo import EscopoCla
from app.models import Missao
from app.repositorios import tarefas as repo_tarefas

MESES = [
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
]


def grade_do_mes(ano: int, mes: int, eventos: dict[date, list]) -> list[list[dict]]:
    """Semanas do mes comecando no domingo, ja com os eventos encaixados em cada dia."""
    semanas = calendar.Calendar(firstweekday=6).monthdatescalendar(ano, mes)
    hoje = date.today()
    return [
        [
            {
                "data": dia,
                "do_mes": dia.month == mes,
                "hoje": dia == hoje,
                "eventos": eventos.get(dia, []),
            }
            for dia in semana
        ]
        for semana in semanas
    ]


def eventos_do_cla(
    escopo: EscopoCla,
    missoes: list[Missao],
    membro_id: int | None = None,
    ano: int | None = None,
    mes: int | None = None,
) -> dict[date, list]:
    """Vencimento de missao e agenda do cla para todo mundo, mais as tarefas de quem esta olhando.

    A agenda so entra com `ano` e `mes`: ela e lida por periodo (ver `agenda.eventos_por_dia`), e
    sem o mes nao ha periodo para ler. Os eventos vem primeiro no dia porque tem hora marcada.
    """
    from app import config

    eventos: dict[date, list] = defaultdict(list)
    if ano and mes and config.AGENDA_ATIVA:
        from app.servicos.agenda import eventos_por_dia, link_google_agenda

        for dia, do_dia in eventos_por_dia(escopo, ano, mes).items():
            for evento in do_dia:
                eventos[dia].append(
                    {
                        "tipo": "evento",
                        "titulo": evento.titulo,
                        "id": evento.id,
                        "hora": evento.inicio.strftime("%H:%M"),
                        "descricao": evento.descricao,
                        "local": evento.local,
                        "duracao_min": evento.duracao_min,
                        "link_google": link_google_agenda(evento),
                    }
                )
    for missao in missoes:
        if missao.vencimento:
            eventos[missao.vencimento].append(
                {"tipo": "missao", "titulo": missao.titulo, "id": missao.id}
            )
    if membro_id is not None:
        from app.models import CONSOME_SALDO, TIPOS_DE_MENTORIA
        from app.repositorios.rastreadores import mentorias_da_pessoa

        # As consultorias sao 1 para 1: so entram no calendario de quem esta olhando, e so quando
        # quem olha e a propria pessoa (membro_id presente). O calendario do cla nao as mostra.
        if escopo.membro_id == membro_id:
            for mentoria in mentorias_da_pessoa(escopo.db, escopo.membro):
                if mentoria.situacao in CONSOME_SALDO:
                    eventos[mentoria.inicio.date()].append(
                        {
                            "tipo": "mentoria",
                            "titulo": TIPOS_DE_MENTORIA.get(mentoria.tipo, "Consultoria"),
                            "id": mentoria.id,
                            "hora": mentoria.inicio.strftime("%H:%M"),
                        }
                    )
        for tarefa in repo_tarefas.do_membro(escopo, membro_id):
            if tarefa.prazo:
                eventos[tarefa.prazo].append(
                    {"tipo": "pessoal", "titulo": tarefa.titulo, "id": tarefa.id}
                )
    return eventos
