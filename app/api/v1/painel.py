"""O painel do cla: numeros, ranking, grafico e calendario. So leitura.

As quatro coisas saem de uma unica leitura das missoes, e e essa a razao de elas estarem juntas numa
rota so. O dashboard em HTML ja funciona assim: antes cada pedaco da pagina buscava a propria copia
das missoes e a mesma consulta saia quatro vezes por carregamento. Quebrar isso em quatro rotas na
API faria a fase 5 refazer o mesmo erro, agora com quatro pedidos de rede em vez de quatro
consultas.

O calendario tem rota propria porque ele e o unico pedaco que muda sozinho: quem clica em "mes
seguinte" nao mudou ranking nenhum.
"""

from datetime import date

from fastapi import APIRouter, Depends

from app.api import saida
from app.api.deps import escopo_api
from app.escopo import EscopoCla
from app.repositorios import entregas as repo_entregas
from app.repositorios import missoes as repo_missoes
from app.servicos.calendario import MESES, eventos_do_cla, grade_do_mes
from app.servicos.ranking import (
    numeros_do_cla,
    progresso_da_missao,
    quem_fez_cada_missao,
    ranking,
)

router = APIRouter(tags=["painel"])


def mes_pedido(ano: int | None, mes: int | None) -> tuple[int, int]:
    """Mes valido, sempre. Mes fora de 1..12 volta para hoje em vez de dar erro.

    O mes chega da URL, e a tela navega somando e subtraindo um: e mais util devolver o mes de hoje
    para quem pediu o mes 13 do que uma pagina de erro no meio da navegacao.
    """
    hoje = date.today()
    ano = ano or hoje.year
    mes = mes or hoje.month
    if not 1 <= mes <= 12:
        return hoje.year, hoje.month
    return ano, mes


@router.get("/painel")
def ver(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """Numeros do cla, ranking, grafico e os cartoes das missoes ativas, de uma leitura so.

    `com_entregas=True` porque o ranking, o grafico e o progresso percorrem `missao.entregas`: sem
    isso o SQLAlchemy vai ao banco uma vez por missao.
    """
    hoje = date.today()
    missoes = repo_missoes.ativas(escopo, com_entregas=True)
    numeros = numeros_do_cla(escopo, missoes)
    minhas = repo_entregas.do_membro(escopo, escopo.membro_id)
    return {
        "numeros": saida.numeros(numeros),
        "ranking": [saida.linha_do_ranking(linha) for linha in ranking(escopo, missoes)],
        "grafico": [
            saida.barra_do_grafico(barra) for barra in quem_fez_cada_missao(escopo, missoes)
        ],
        "missoes": [
            {
                "missao": saida.missao(m),
                "progresso": progresso_da_missao(m, numeros["total_membros"]),
                "minha_entrega": saida.entrega(minhas.get(m.id)),
                "dias": (m.vencimento - hoje).days if m.vencimento else None,
            }
            for m in missoes
        ],
    }


@router.get("/calendario")
def calendario(
    ano: int | None = None,
    mes: int | None = None,
    so_meus: bool = False,
    escopo: EscopoCla = Depends(escopo_api),
) -> dict:
    """A grade do mes, com as semanas comecando no domingo, do jeito que a tela desenha.

    A grade vem montada do servidor porque ela e calendario de verdade (dias de outro mes que
    aparecem na primeira e na ultima semana, semana que comeca no domingo) e nao lista de eventos.
    Remontar isso no navegador seria reescrever o `calendar` do Python em TypeScript para chegar na
    mesma tabela.

    `so_meus` e o que o quadro pessoal usa: la o calendario mostra as missoes do cla junto com as
    tarefas de quem esta olhando, e no painel ele mostra o cla inteiro.
    """
    ano, mes = mes_pedido(ano, mes)
    missoes = repo_missoes.ativas(escopo)
    eventos = eventos_do_cla(escopo, missoes, escopo.membro_id if so_meus else None, ano, mes)
    semanas = grade_do_mes(ano, mes, eventos)
    return {
        "ano": ano,
        "mes": mes,
        "mes_nome": MESES[mes - 1],
        "mes_anterior": list((ano - 1, 12) if mes == 1 else (ano, mes - 1)),
        "mes_seguinte": list((ano + 1, 1) if mes == 12 else (ano, mes + 1)),
        "semanas": [[saida.dia_do_calendario(dia) for dia in semana] for semana in semanas],
    }
