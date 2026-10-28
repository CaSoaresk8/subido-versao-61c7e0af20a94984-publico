"""A lixeira e o log do cla. As duas restauracoes chamam o mesmo servico que a API chama."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import config
from app.deps import escopo_logado, templates
from app.escopo import EscopoCla
from app.repositorios import eventos as repo_eventos
from app.repositorios import logs as repo_logs
from app.repositorios import missoes as repo_missoes
from app.repositorios import tarefas as repo_tarefas
from app.servicos import agenda as servico_agenda
from app.servicos import missoes as servico_missoes
from app.servicos import tarefas as servico_tarefas

router = APIRouter(prefix="/historico")


@router.get("")
def ver(
    request: Request,
    escopo: EscopoCla = Depends(escopo_logado),
):
    return templates.TemplateResponse(
        request,
        "historico.html",
        {
            "membro": escopo.membro,
            "missoes": repo_missoes.na_lixeira(escopo),
            "eventos": repo_eventos.na_lixeira(escopo),
            "mostrar_eventos": config.AGENDA_ATIVA,
            # Missao excluida todo mundo do cla ve e pode restaurar; tarefa pessoal so o dono.
            "tarefas": repo_tarefas.na_lixeira_do_membro(escopo, escopo.membro_id),
            "logs": repo_logs.recentes(escopo),
        },
    )


@router.post("/missoes/{missao_id}/restaurar")
def restaurar_missao(
    missao_id: int,
    escopo: EscopoCla = Depends(escopo_logado),
):
    missao = repo_missoes.por_id(escopo, missao_id)
    if missao is None:
        raise HTTPException(status_code=404, detail="Missão não encontrada na lixeira")
    # Missao que ja esta fora da lixeira cai no mesmo 404, levantado la dentro pelo servico.
    servico_missoes.restaurar(escopo, missao)
    escopo.db.commit()
    return RedirectResponse(f"/missoes/{missao.id}", status_code=303)


@router.post("/tarefas/{tarefa_id}/restaurar")
def restaurar_tarefa(
    tarefa_id: int,
    escopo: EscopoCla = Depends(escopo_logado),
):
    servico_tarefas.restaurar(escopo, tarefa_id)
    escopo.db.commit()
    return RedirectResponse("/minhas", status_code=303)


@router.post("/eventos/{evento_id}/restaurar")
def restaurar_evento(
    evento_id: int,
    escopo: EscopoCla = Depends(escopo_logado),
):
    """Volta para a agenda e, se o cla tem conta Google, o convite sai de novo para todo mundo."""
    if not config.AGENDA_ATIVA:
        raise HTTPException(status_code=404, detail="Página não encontrada")
    evento = repo_eventos.por_id(escopo, evento_id)
    if evento is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado na lixeira")
    servico_agenda.restaurar(escopo, evento)
    escopo.db.commit()
    return RedirectResponse(f"/agenda/{evento.id}", status_code=303)
