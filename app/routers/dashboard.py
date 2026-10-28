from datetime import date

from fastapi import APIRouter, Depends, Request

from app.deps import escopo_logado, templates
from app.escopo import EscopoCla
from app.repositorios import entregas as repo_entregas
from app.repositorios import missoes as repo_missoes
from app.servicos.acompanhamento import resumo_da_semana
from app.servicos.calendario import MESES, eventos_do_cla, grade_do_mes
from app.servicos.ranking import (
    numeros_do_cla,
    progresso_da_missao,
    quem_fez_cada_missao,
    ranking,
)

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    ano: int | None = None,
    mes: int | None = None,
    escopo: EscopoCla = Depends(escopo_logado),
):
    membro = escopo.membro
    hoje = date.today()
    ano = ano or hoje.year
    mes = mes or hoje.month
    if not 1 <= mes <= 12:
        ano, mes = hoje.year, hoje.month

    # As missoes sao lidas UMA vez e passadas adiante. Antes cada pedaco da pagina (numeros,
    # ranking, grafico, calendario, lista) buscava a propria copia, e a mesma consulta saia quatro
    # vezes por carregamento. com_entregas=True porque o ranking, o grafico e o progresso percorrem
    # missao.entregas: sem isso o SQLAlchemy vai ao banco uma vez por missao.
    missoes = repo_missoes.ativas(escopo, com_entregas=True)
    numeros = numeros_do_cla(escopo, missoes)
    minhas = repo_entregas.do_membro(escopo, membro.id)
    cartoes = [
        {
            "missao": missao,
            "progresso": progresso_da_missao(missao, numeros["total_membros"]),
            "minha_entrega": minhas.get(missao.id),
            "dias": (missao.vencimento - hoje).days if missao.vencimento else None,
        }
        for missao in missoes
    ]

    mes_anterior = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    mes_seguinte = (ano + 1, 1) if mes == 12 else (ano, mes + 1)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "membro": membro,
            "numeros": numeros,
            "ranking": ranking(escopo, missoes),
            "grafico": quem_fez_cada_missao(escopo, missoes),
            "missoes": cartoes,
            "semanas": grade_do_mes(ano, mes, eventos_do_cla(escopo, missoes, membro.id, ano, mes)),
            "mes_nome": MESES[mes - 1],
            "ano": ano,
            "mes": mes,
            "mes_anterior": mes_anterior,
            "mes_seguinte": mes_seguinte,
            # O aviso de quem assumiu a semana: o app nao manda lembrete por fora, entao e aqui,
            # na primeira tela, que a pessoa descobre quantas conversas faltam.
            "semana": resumo_da_semana(escopo),
        },
    )
