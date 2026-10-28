"""A lixeira e o log do cla.

Missao excluida todo mundo do cla ve e pode restaurar; tarefa pessoal so o dono. A diferenca nao e
detalhe de tela: a missao e do cla, e apagar a de outra pessoa por engano tem que ter volta por
qualquer um; a tarefa e privada, e listar a dos outros seria mostrar o que ninguem mais deveria ver.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api import saida
from app.api.deps import escopo_api, exige_origem_propria
from app.escopo import EscopoCla
from app.repositorios import eventos as repo_eventos
from app.repositorios import logs as repo_logs
from app.repositorios import missoes as repo_missoes
from app.repositorios import tarefas as repo_tarefas
from app.servicos import agenda as servico_agenda
from app.servicos import missoes as servico_missoes
from app.servicos import tarefas as servico_tarefas

router = APIRouter(tags=["historico"])


@router.get("/historico")
def ver(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """O que esta na lixeira e o que aconteceu no cla.

    `excluida_por` sai aqui e nao dentro de `saida.missao`: so esta tela mostra quem apagou, e o
    campo custa uma leitura a mais por missao. Carrega-lo no formato comum faria toda listagem de
    missao ativa pagar por uma informacao que so existe para missao excluida.
    """
    na_lixeira = repo_missoes.na_lixeira(escopo)
    return {
        "missoes": [
            {
                **saida.missao(m),
                "excluida_por": saida.membro(m.excluida_por) if m.excluida_por else None,
            }
            for m in na_lixeira
        ],
        "eventos": [saida.evento(e) for e in repo_eventos.na_lixeira(escopo)],
        "tarefas": [
            saida.tarefa(t) for t in repo_tarefas.na_lixeira_do_membro(escopo, escopo.membro_id)
        ],
        "logs": [saida.log(registro) for registro in repo_logs.recentes(escopo)],
    }


@router.post(
    "/historico/missoes/{missao_id}/restaurar", dependencies=[Depends(exige_origem_propria)]
)
def restaurar_missao(missao_id: int, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    missao = repo_missoes.por_id(escopo, missao_id)
    if missao is None:
        raise HTTPException(status_code=404, detail="Missão não encontrada na lixeira")
    # Missao que ja esta fora da lixeira cai no mesmo 404, levantado la dentro pelo servico.
    servico_missoes.restaurar(escopo, missao)
    escopo.db.commit()
    return saida.missao(missao)


@router.post(
    "/historico/tarefas/{tarefa_id}/restaurar", dependencies=[Depends(exige_origem_propria)]
)
def restaurar_tarefa(tarefa_id: int, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    tarefa = servico_tarefas.restaurar(escopo, tarefa_id)
    escopo.db.commit()
    return saida.tarefa(tarefa)


@router.post(
    "/historico/eventos/{evento_id}/restaurar", dependencies=[Depends(exige_origem_propria)]
)
def restaurar_evento(evento_id: int, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    evento = repo_eventos.por_id(escopo, evento_id)
    if evento is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado na lixeira")
    servico_agenda.restaurar(escopo, evento)
    escopo.db.commit()
    return saida.evento(evento)
