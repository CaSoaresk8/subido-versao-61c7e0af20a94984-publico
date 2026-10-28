"""Colunas que o membro cria no proprio quadro: criar, reordenar e apagar.

Como nos outros servicos, nada aqui da commit. A excecao anotada e o `flush()` de `excluir`, que
nao e commit e sim ordem de operacoes dentro da mesma transacao.
"""

from __future__ import annotations

from app.escopo import EscopoCla
from app.models import A_FAZER, STATUS_VALIDOS, Coluna
from app.repositorios import colunas as repo_colunas
from app.repositorios import entregas as repo_entregas
from app.repositorios import tarefas as repo_tarefas
from app.servicos.erros import ForaDeRegra, NaoEncontrado

MAXIMO_NOME = 60
# Oito e o que cabe no scroll horizontal do celular sem o quadro virar uma fita infinita. Nao e
# limite de banco: e limite de tela.
MAX_COLUNAS = 8


def criar(escopo: EscopoCla, nome: str) -> Coluna:
    nome = nome.strip()[:MAXIMO_NOME]
    if not nome:
        raise ForaDeRegra("Escreva um nome para a coluna.")
    if len(repo_colunas.do_membro(escopo, escopo.membro_id)) >= MAX_COLUNAS:
        raise ForaDeRegra(f"O quadro aceita no máximo {MAX_COLUNAS} colunas suas.")
    coluna = Coluna(
        cla_id=escopo.cla_id,
        membro_id=escopo.membro_id,
        nome=nome,
        ordem=repo_colunas.maior_ordem(escopo, escopo.membro_id) + 1,
    )
    escopo.db.add(coluna)
    escopo.db.flush()
    return coluna


def reordenar(escopo: EscopoCla, pedidas: list) -> str:
    """Guarda a ordem em que o membro arrastou as colunas. Devolve a ordem gravada.

    A lista pedida e filtrada contra o que existe de verdade (as tres etapas padrao mais as colunas
    do proprio membro) e so entao conferida: uma ordem que nao cite todas seria gravada pela metade,
    e a metade que faltasse cairia no fim do quadro na proxima vez que a pessoa abrisse, sem ela ter
    pedido nada disso.
    """
    minhas = repo_colunas.do_membro(escopo, escopo.membro_id)
    validas = set(STATUS_VALIDOS) | {f"c{coluna.id}" for coluna in minhas}
    ordem = [str(chave) for chave in pedidas if str(chave) in validas]
    if len(set(ordem)) != len(validas):
        raise ForaDeRegra("Ordem incompleta")
    escopo.membro.ordem_quadro = ",".join(dict.fromkeys(ordem))
    return escopo.membro.ordem_quadro


def excluir(escopo: EscopoCla, coluna_id: int) -> None:
    """Apaga a coluna e devolve os cartoes dela para "A fazer", em vez de apagar os cartoes junto.

    E a unica exclusao do app que e DELETE de verdade e nao marcacao: a coluna e um agrupamento
    vazio de significado proprio, e nao ha o que restaurar depois. O que nao pode sumir junto e o
    que estava dentro dela.
    """
    coluna = repo_colunas.por_id(escopo, coluna_id)
    if coluna is None or coluna.membro_id != escopo.membro_id:
        raise NaoEncontrado("Coluna não encontrada")

    for entrega in repo_entregas.na_coluna(escopo, coluna.id):
        entrega.coluna_id = None
        entrega.status = A_FAZER
        entrega.concluida_em = None
    for tarefa in repo_tarefas.na_coluna(escopo, coluna.id):
        tarefa.coluna_id = None
        tarefa.status = A_FAZER

    membro = escopo.membro
    chave = f"c{coluna.id}"
    membro.ordem_quadro = ",".join(c for c in membro.ordem_quadro.split(",") if c and c != chave)
    # Os cartoes acima precisam soltar a coluna ANTES do DELETE chegar no banco. Nao existe
    # relationship entre Coluna e Entrega/TarefaPessoal, entao o SQLAlchemy nao sabe dessa ordem e
    # manda o DELETE primeiro. Com PRAGMA foreign_keys=ON isso estoura na hora.
    escopo.db.flush()
    escopo.db.delete(coluna)
