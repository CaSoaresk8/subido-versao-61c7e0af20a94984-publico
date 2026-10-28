"""Regra do quadro pessoal: o que e cartao, onde ele esta e quanto vale.

Tudo aqui roda sem servidor no ar. Era o ponto do split: `montar_quadro`, `resolver_destino` e
`colocar` sao a parte que de fato pode dar errado, e enquanto moravam dentro do router so davam
para testar por HTTP.

Nenhuma funcao recebe mais `db` e `membro` soltos: recebem o escopo, que carrega os dois junto com
o cla. Era possivel passar a sessao de um pedido com o membro de outro, e agora nao e.
"""

from __future__ import annotations

from datetime import date

from app.escopo import EscopoCla
from app.models import (
    A_FAZER,
    CONCLUIDO,
    FAZENDO,
    STATUS_LABEL,
    STATUS_VALIDOS,
    Coluna,
    Missao,
    agora,
)
from app.repositorios import colunas as repo_colunas
from app.repositorios import entregas as repo_entregas
from app.repositorios import missoes as repo_missoes
from app.repositorios import tarefas as repo_tarefas
from app.servicos.auditoria import registrar
from app.servicos.erros import DestinoInvalido
from app.servicos.missoes import falta_resposta
from app.servicos.tarefas import minha_tarefa

VISOES = ("kanban", "lista", "calendario")
PADRAO = (A_FAZER, FAZENDO, CONCLUIDO)


def montar_itens(escopo: EscopoCla, ids_colunas: set[int], missoes: list[Missao]) -> list[dict]:
    """Missoes do cla mais as tarefas so do membro, ja com onde cada cartao esta.

    A lista de missoes chega pronta de fora porque quem chama tambem precisa dela (para o
    calendario), e buscar duas vezes a mesma coisa e o tipo de desperdicio que so aparece quando
    ja tem muito cla no banco.
    """
    entregas = repo_entregas.do_membro(escopo, escopo.membro_id)
    itens = []
    for missao in missoes:
        entrega = entregas.get(missao.id)
        coluna_id = entrega.coluna_id if entrega else None
        itens.append(
            {
                "tipo": "missao",
                "id": missao.id,
                "chave": f"missao-{missao.id}",
                "titulo": missao.titulo,
                "descricao": missao.descricao,
                "status": entrega.status if entrega else A_FAZER,
                "prazo": missao.vencimento,
                "pontos": missao.pontos,
                "url": f"/missoes/{missao.id}",
                "resposta": entrega.resposta if entrega else "",
                "coluna_id": coluna_id if coluna_id in ids_colunas else None,
                "ordem": entrega.ordem if entrega else 0,
            }
        )
    tarefas = repo_tarefas.do_membro(escopo, escopo.membro_id)
    from app.repositorios.rastreadores import nomes_de_rastreadores

    mentores = nomes_de_rastreadores(
        escopo.db, {t.criada_por_rastreador_id for t in tarefas if t.criada_por_rastreador_id}
    )
    for tarefa in tarefas:
        itens.append(
            {
                "tipo": "pessoal",
                "id": tarefa.id,
                "chave": f"pessoal-{tarefa.id}",
                "titulo": tarefa.titulo,
                "descricao": tarefa.descricao,
                "status": tarefa.status,
                "prazo": tarefa.prazo,
                "pontos": 0,
                "url": "/minhas",
                "resposta": "",
                "coluna_id": tarefa.coluna_id if tarefa.coluna_id in ids_colunas else None,
                "ordem": tarefa.ordem,
                # Quem da mentoria criou, quando nao foi a propria pessoa. E o que responde "de
                # onde veio este cartao que eu nao criei" sem ela precisar perguntar.
                "mentor": mentores.get(tarefa.criada_por_rastreador_id, ""),
            }
        )
    itens.sort(key=lambda i: (i["prazo"] is None, i["prazo"] or date.max, i["titulo"]))
    return itens


def _ordenar_grupos(grupos: list[dict], ordem_salva: str) -> list[dict]:
    """Respeita a ordem que o membro arrastou. Coluna nova entra no fim."""
    preferida = [chave for chave in ordem_salva.split(",") if chave]
    posicao = {chave: indice for indice, chave in enumerate(preferida)}
    return sorted(grupos, key=lambda g: (posicao.get(g["chave"], len(posicao) + grupos.index(g)),))


def montar_quadro(itens: list[dict], colunas: list[Coluna], ordem_salva: str = "") -> list[dict]:
    def do_grupo(selecao):
        return sorted(selecao, key=lambda i: (i["ordem"], i["titulo"]))

    grupos = [
        {
            "chave": status,
            "nome": STATUS_LABEL[status],
            "padrao": True,
            "id": None,
            "itens": do_grupo(
                [i for i in itens if i["coluna_id"] is None and i["status"] == status]
            ),
        }
        for status in PADRAO
    ]
    grupos += [
        {
            "chave": f"c{coluna.id}",
            "nome": coluna.nome,
            "padrao": False,
            "id": coluna.id,
            "itens": do_grupo([i for i in itens if i["coluna_id"] == coluna.id]),
        }
        for coluna in colunas
    ]
    return _ordenar_grupos(grupos, ordem_salva)


def pontos(itens: list[dict]) -> int:
    return sum(i["pontos"] for i in itens if i["coluna_id"] is None and i["status"] == CONCLUIDO)


def resolver_destino(escopo: EscopoCla, destino: str) -> tuple[int | None, str]:
    """Devolve (coluna_id, status). Coluna criada pelo membro nao pontua, entao volta a a_fazer."""
    if destino in STATUS_VALIDOS:
        return None, destino
    if destino.startswith("c") and destino[1:].isdigit():
        coluna = repo_colunas.por_id(escopo, int(destino[1:]))
        if coluna is not None and coluna.membro_id == escopo.membro_id:
            return coluna.id, A_FAZER
    raise DestinoInvalido("Destino invalido")


def colocar(
    escopo: EscopoCla, chave: str, coluna_id: int | None, status: str, ordem: int
) -> Missao | None:
    """Move o cartao. Devolve a missao que barrou o movimento, quando ela exige resposta."""
    tipo, _, ident = chave.partition("-")
    if not ident.isdigit():
        return None

    if tipo == "missao":
        missao = repo_missoes.por_id(escopo, int(ident))
        if missao is None or not missao.ativa:
            return None
        entrega = repo_entregas.obter_ou_criar(escopo, missao.id, escopo.membro_id)
        if status == CONCLUIDO and coluna_id is None and falta_resposta(missao, entrega):
            return missao
        mudou = entrega.status != status or entrega.coluna_id != coluna_id
        entrega.coluna_id = coluna_id
        entrega.status = status
        entrega.ordem = ordem
        entrega.concluida_em = agora() if status == CONCLUIDO and coluna_id is None else None
        if mudou:
            registrar(escopo, "atualizou", "entrega", entrega.id, f"{missao.titulo}: {status}")
    elif tipo == "pessoal":
        tarefa = minha_tarefa(escopo, int(ident))
        tarefa.coluna_id = coluna_id
        tarefa.status = status
        tarefa.ordem = ordem
    return None


def mover(escopo: EscopoCla, destino: str, chaves: list) -> Missao | None:
    """Poe a coluna inteira na ordem recebida. Devolve a missao que barrou, ou None quando deu certo.

    Recebe a coluna toda, e nao o cartao que se moveu, porque soltar um cartao no meio de uma pilha
    muda a posicao de todos os que estao abaixo dele. Mandar so o que mudou obrigaria os dois lados
    a concordar sobre como as posicoes se deslocam, e essa e uma conta que sai diferente em cada
    lugar que a refaz.

    O rollback fica aqui dentro por causa do que `colocar` deixa pelo caminho: ele ja escreveu nos
    cartoes anteriores da lista quando o quinto barra, e sair sem desfazer gravaria um movimento
    pela metade. Quem chama so precisa dar commit quando a resposta for None. O commit fica de fora
    pela regra que vale em todos os servicos: quem chamou e quem sabe se a operacao inteira vale.
    """
    coluna_id, status = resolver_destino(escopo, destino)
    for ordem, chave in enumerate(chaves):
        barrou = colocar(escopo, str(chave), coluna_id, status, ordem)
        if barrou is not None:
            escopo.db.rollback()
            return barrou
    return None
