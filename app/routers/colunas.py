"""As telas das colunas do quadro. A regra mora em `servicos/colunas.py`.

`?erro=coluna` e `?erro=limite` continuam sendo os dois codigos que o quadro sabe desenhar, e por
isso a recusa do servico e traduzida para eles aqui: a frase pronta e do JSON, a URL curta e do
HTML. As duas saem da mesma decisao.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.deps import escopo_logado
from app.escopo import EscopoCla
from app.servicos import colunas as servico_colunas
from app.servicos.erros import ForaDeRegra

router = APIRouter(prefix="/minhas/colunas")


@router.post("")
def criar_coluna(
    nome: str = Form(...),
    escopo: EscopoCla = Depends(escopo_logado),
):
    try:
        servico_colunas.criar(escopo, nome)
    except ForaDeRegra:
        codigo = "coluna" if not nome.strip() else "limite"
        return RedirectResponse(f"/minhas?visao=kanban&erro={codigo}", status_code=303)
    escopo.db.commit()
    return RedirectResponse("/minhas?visao=kanban", status_code=303)


@router.post("/ordenar")
async def ordenar_colunas(
    request: Request,
    escopo: EscopoCla = Depends(escopo_logado),
):
    dados = await request.json()
    pedidas = dados.get("colunas")
    if not isinstance(pedidas, list):
        raise HTTPException(status_code=400, detail="Lista de colunas inválida")
    try:
        servico_colunas.reordenar(escopo, pedidas)
    except ForaDeRegra as recusa:
        raise HTTPException(status_code=400, detail=str(recusa)) from recusa
    escopo.db.commit()
    return JSONResponse({"ok": True})


@router.post("/{coluna_id}/excluir")
def excluir_coluna(
    coluna_id: int,
    escopo: EscopoCla = Depends(escopo_logado),
):
    servico_colunas.excluir(escopo, coluna_id)
    escopo.db.commit()
    return RedirectResponse("/minhas?visao=kanban", status_code=303)
