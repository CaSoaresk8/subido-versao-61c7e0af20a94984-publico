"""A tarefa pessoal: a que so o dono ve.

Nenhuma rota daqui aceita um `membro_id`. A tarefa e sempre a de quem pediu, e quem diz quem pediu
e o escopo. `servicos/tarefas.py:minha_tarefa` e o unico caminho ate uma tarefa por id, e la dentro
nao existir, ser de outra pessoa e estar na lixeira dao o mesmo 404.
"""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api import saida
from app.api.deps import escopo_api, exige_origem_propria
from app.escopo import EscopoCla
from app.models import A_FAZER
from app.repositorios import tarefas as repo_tarefas
from app.servicos import tarefas as servico_tarefas
from app.servicos.quadro import resolver_destino

router = APIRouter(tags=["tarefas"])


class TarefaNova(BaseModel):
    titulo: str
    descricao: str = ""
    prazo: date | None = None
    # A chave da coluna do quadro ("a_fazer", "fazendo", "concluido" ou "c7"), do mesmo jeito que o
    # kanban ja nomeia os grupos. Vazio cria em "A fazer".
    destino: str = ""


class TarefaEditada(BaseModel):
    titulo: str
    prazo: date | None = None


@router.get("/tarefas")
def listar(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    return {"tarefas": [saida.tarefa(t) for t in repo_tarefas.do_membro(escopo, escopo.membro_id)]}


@router.post("/tarefas", status_code=201, dependencies=[Depends(exige_origem_propria)])
def criar(pedido: TarefaNova, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """Cria a tarefa, ja na coluna pedida. `destino` invalido da 400, vindo de `resolver_destino`.

    O destino e resolvido aqui e nao no servico porque ele e vocabulario do quadro: "c7" so quer
    dizer alguma coisa para quem desenha colunas. O servico recebe coluna_id e status, que e o que
    a tarefa de fato guarda.
    """
    coluna_id, status = (
        resolver_destino(escopo, pedido.destino) if pedido.destino else (None, A_FAZER)
    )
    tarefa = servico_tarefas.criar(
        escopo,
        titulo=pedido.titulo,
        descricao=pedido.descricao,
        prazo=pedido.prazo,
        coluna_id=coluna_id,
        status=status,
    )
    escopo.db.commit()
    return saida.tarefa(tarefa)


@router.put("/tarefas/{tarefa_id}", dependencies=[Depends(exige_origem_propria)])
def editar(tarefa_id: int, pedido: TarefaEditada, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    tarefa = servico_tarefas.minha_tarefa(escopo, tarefa_id)
    servico_tarefas.editar(escopo, tarefa, pedido.titulo, pedido.prazo)
    escopo.db.commit()
    return saida.tarefa(tarefa)


@router.delete("/tarefas/{tarefa_id}", dependencies=[Depends(exige_origem_propria)])
def excluir(tarefa_id: int, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """Manda para a lixeira, como a missao. Da para restaurar pelo historico."""
    tarefa = servico_tarefas.minha_tarefa(escopo, tarefa_id)
    servico_tarefas.excluir(escopo, tarefa)
    escopo.db.commit()
    return saida.tarefa(tarefa)
