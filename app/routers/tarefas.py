"""As telas da tarefa pessoal. A regra mora em `servicos/tarefas.py`.

Erro aqui nao vira pagina de erro: vira volta para o quadro com `?erro=` na URL, porque o
formulario de tarefa esta dentro da propria coluna do kanban e nao tem tela propria para onde
voltar. `app/api/v1/tarefas.py` chama os mesmos servicos e responde 400 com a frase.
"""

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse

from app.deps import escopo_logado
from app.escopo import EscopoCla
from app.models import A_FAZER
from app.servicos import tarefas as servico_tarefas
from app.servicos.erros import ForaDeRegra
from app.servicos.quadro import resolver_destino

router = APIRouter(prefix="/minhas/tarefas")


@router.post("")
def criar_tarefa(
    titulo: str = Form(...),
    descricao: str = Form(""),
    prazo: str = Form(""),
    visao: str = Form("kanban"),
    destino: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    coluna_id, status = resolver_destino(escopo, destino) if destino else (None, A_FAZER)
    try:
        servico_tarefas.criar(
            escopo,
            titulo=titulo,
            descricao=descricao,
            prazo=servico_tarefas.data_ou_nada(prazo),
            coluna_id=coluna_id,
            status=status,
        )
    except ForaDeRegra:
        return RedirectResponse(f"/minhas?visao={visao}&erro=titulo", status_code=303)
    escopo.db.commit()
    return RedirectResponse(f"/minhas?visao={visao}", status_code=303)


@router.post("/{tarefa_id}/editar")
def editar_tarefa(
    tarefa_id: int,
    titulo: str = Form(...),
    prazo: str = Form(""),
    visao: str = Form("kanban"),
    escopo: EscopoCla = Depends(escopo_logado),
):
    tarefa = servico_tarefas.minha_tarefa(escopo, tarefa_id)
    try:
        servico_tarefas.editar(escopo, tarefa, titulo, servico_tarefas.data_ou_nada(prazo))
    except ForaDeRegra:
        return RedirectResponse(f"/minhas?visao={visao}&erro=titulo", status_code=303)
    escopo.db.commit()
    return RedirectResponse(f"/minhas?visao={visao}", status_code=303)


@router.post("/{tarefa_id}/excluir")
def excluir_tarefa(
    tarefa_id: int,
    visao: str = Form("kanban"),
    escopo: EscopoCla = Depends(escopo_logado),
):
    tarefa = servico_tarefas.minha_tarefa(escopo, tarefa_id)
    servico_tarefas.excluir(escopo, tarefa)
    escopo.db.commit()
    return RedirectResponse(f"/minhas?visao={visao}", status_code=303)
