"""Placar, relatorio por pessoa e numeros do cla.

Ponto nenhum fica gravado: o placar e sempre recalculado a partir de onde o cartao esta agora. E
por isso que arrastar o cartao para fora de Concluido tira os pontos na hora, sem nada para
sincronizar depois.
"""

from collections import defaultdict
from datetime import date

from app.escopo import EscopoCla
from app.models import A_FAZER, CONCLUIDO, FAZENDO, Entrega, Missao
from app.repositorios import entregas as repo_entregas
from app.repositorios import membros as repo_membros
from app.servicos.missoes import conta_como_concluida


def relatorio(missoes: list[Missao], entregas: dict[int, Entrega]) -> dict:
    """Missoes de um membro separadas por etapa, com os pontos que elas valem.

    So missao entra aqui. Tarefa pessoal e do dono e mais ninguem ve, entao nem chega nesta
    funcao. Cartao que o membro guardou numa coluna criada por ele conta como nao comecado, e a
    coluna nunca aparece: e o mesmo criterio que vale para pontuar.
    """
    etapas: dict[str, list] = {CONCLUIDO: [], FAZENDO: [], A_FAZER: []}
    pontos = 0
    for missao in missoes:
        entrega = entregas.get(missao.id)
        etapa = entrega.status if entrega and entrega.coluna_id is None else A_FAZER
        if etapa not in etapas:
            etapa = A_FAZER
        if conta_como_concluida(entrega):
            pontos += missao.pontos
        etapas[etapa].append({"missao": missao, "entrega": entrega})

    return {
        "pontos": pontos,
        "concluidas": etapas[CONCLUIDO],
        "fazendo": etapas[FAZENDO],
        "a_fazer": etapas[A_FAZER],
        "total_missoes": sum(len(v) for v in etapas.values()),
    }


def ranking(escopo: EscopoCla, missoes: list[Missao]) -> list[dict]:
    """Uma linha por membro, ja com o relatorio que abre dentro dela.

    Empate divide a posicao: dois com os mesmos pontos ficam os dois em segundo, e o proximo em
    quarto.
    """
    membros = repo_membros.todos(escopo)

    por_membro: dict[int, dict[int, Entrega]] = defaultdict(dict)
    ultima: dict[int, object] = {}
    for entrega in repo_entregas.de_missoes_ativas(escopo):
        por_membro[entrega.membro_id][entrega.missao_id] = entrega
        anterior = ultima.get(entrega.membro_id)
        if anterior is None or entrega.atualizada_em > anterior:
            ultima[entrega.membro_id] = entrega.atualizada_em

    linhas = []
    for membro in membros:
        # Uma fonte so: os pontos da linha e o relatorio que abre nela saem da mesma conta.
        rel = relatorio(missoes, por_membro[membro.id])
        linhas.append(
            {
                "membro": membro,
                "pontos": rel["pontos"],
                "concluidas": len(rel["concluidas"]),
                "pendentes": len(missoes) - len(rel["concluidas"]),
                "ultima_atividade": ultima.get(membro.id),
                "relatorio": rel,
            }
        )
    linhas.sort(key=lambda linha: (-linha["pontos"], linha["membro"].nome))

    posicao = 0
    pontos_anteriores = None
    for indice, linha in enumerate(linhas, start=1):
        if linha["pontos"] != pontos_anteriores:
            posicao = indice
            pontos_anteriores = linha["pontos"]
        linha["posicao"] = posicao
    return linhas


def numeros_do_cla(escopo: EscopoCla, missoes: list[Missao]) -> dict:
    total_membros = repo_membros.total(escopo)
    potencial = sum(m.pontos for m in missoes) * total_membros
    gerados, concluidas = repo_entregas.pontuacao_concluida(escopo)

    entregas_possiveis = total_membros * len(missoes)
    hoje = date.today()
    return {
        "total_membros": total_membros,
        "total_missoes": len(missoes),
        "pontos_gerados": gerados,
        "pontos_potenciais": potencial,
        "aproveitamento": round(gerados / potencial * 100, 1) if potencial else 0.0,
        "entregas_concluidas": concluidas,
        "entregas_possiveis": entregas_possiveis,
        "conclusao": round(concluidas / entregas_possiveis * 100, 1) if entregas_possiveis else 0.0,
        "vencendo": [m for m in missoes if m.vencimento and 0 <= (m.vencimento - hoje).days <= 7],
        "vencidas": [m for m in missoes if m.vencimento and m.vencimento < hoje],
    }


def progresso_da_missao(missao: Missao, total_membros: int) -> dict:
    """Le missao.entregas: quem chama tem que ter carregado a missao com com_entregas=True."""
    feitas = sum(1 for e in missao.entregas if conta_como_concluida(e))
    return {
        "feitas": feitas,
        "total": total_membros,
        "percentual": round(feitas / total_membros * 100) if total_membros else 0,
    }


def quem_fez_cada_missao(escopo: EscopoCla, missoes: list[Missao]) -> list[dict]:
    """Uma barra por missao: quantos concluiram e quem sao, para o grafico do dashboard."""
    nomes = repo_membros.nomes(escopo)
    total_membros = len(nomes)

    dados = []
    for missao in missoes:
        feitas = sorted(
            (
                {"id": e.membro_id, "nome": nomes.get(e.membro_id, "membro removido")}
                for e in missao.entregas
                if conta_como_concluida(e)
            ),
            key=lambda q: q["nome"],
        )
        dados.append(
            {
                "missao": missao,
                "quantidade": len(feitas),
                "quem": feitas,
                # Percentual do maior valor possivel, para as barras serem comparaveis entre si.
                "percentual": round(len(feitas) / total_membros * 100) if total_membros else 0,
            }
        )
    dados.sort(key=lambda d: (-d["quantidade"], d["missao"].titulo))
    return dados
