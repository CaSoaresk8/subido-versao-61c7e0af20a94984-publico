"""Quem esta no cla ativo.

So leitura. Nao ha rota de expulsar nem de promover, e nao e esquecimento: o cla foi pedido sem
lider, entao nao existe quem tenha o poder de tirar alguem. Sair de um cla, quando existir, sera
uma rota sobre a PROPRIA participacao, e nao sobre a dos outros.
"""

from fastapi import APIRouter, Depends

from app.api import saida
from app.api.deps import escopo_api
from app.escopo import EscopoCla
from app.repositorios import membros as repo_membros

router = APIRouter(tags=["membros"])


@router.get("/membros")
def listar(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    registros = repo_membros.todos(escopo)
    return {"membros": [saida.membro_do_cla(m) for m in registros], "total": len(registros)}
