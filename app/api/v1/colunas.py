"""As colunas que o membro cria no proprio quadro, e a ordem em que ele as arrastou.

Coluna e do MEMBRO, nao do cla: ninguem mais ve as suas. E por isso que `excluir` devolve os
cartoes para "A fazer" em vez de apagar junto, e por isso que a ordem mora em `membro.ordem_quadro`.
"""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.api import saida
from app.api.deps import escopo_api, exige_origem_propria
from app.escopo import EscopoCla
from app.repositorios import colunas as repo_colunas
from app.servicos import colunas as servico_colunas

router = APIRouter(tags=["colunas"])


class ColunaNova(BaseModel):
    nome: str


class OrdemDasColunas(BaseModel):
    """As chaves do quadro inteiro, na ordem: as tres etapas padrao mais as colunas suas.

    A lista vem completa de proposito. Uma ordem que nao cite todas seria gravada pela metade, e a
    metade que faltasse cairia no fim do quadro na proxima vez que a pessoa abrisse, sem ela ter
    pedido nada disso.
    """

    colunas: list[str]


@router.get("/colunas")
def listar(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    minhas = repo_colunas.do_membro(escopo, escopo.membro_id)
    return {
        "colunas": [saida.coluna(c) for c in minhas],
        "ordem": escopo.membro.ordem_quadro,
        "maximo": servico_colunas.MAX_COLUNAS,
        "pode_criar": len(minhas) < servico_colunas.MAX_COLUNAS,
    }


@router.post("/colunas", status_code=201, dependencies=[Depends(exige_origem_propria)])
def criar(pedido: ColunaNova, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """Nome vazio e limite estourado dao 400 com a frase do servico, vinda do ForaDeRegra."""
    coluna = servico_colunas.criar(escopo, pedido.nome)
    escopo.db.commit()
    return saida.coluna(coluna)


@router.put("/colunas/ordem", dependencies=[Depends(exige_origem_propria)])
def ordenar(pedido: OrdemDasColunas, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    ordem = servico_colunas.reordenar(escopo, pedido.colunas)
    escopo.db.commit()
    return {"ordem": ordem}


@router.delete(
    "/colunas/{coluna_id}", status_code=204, dependencies=[Depends(exige_origem_propria)]
)
def excluir(coluna_id: int, escopo: EscopoCla = Depends(escopo_api)) -> Response:
    """A unica exclusao do app que e DELETE de verdade, e por isso a unica que devolve 204.

    Nao ha o que restaurar: a coluna e um agrupamento sem significado proprio. O que estava dentro
    dela volta para "A fazer" em vez de sumir junto, e isso o servico garante.
    """
    servico_colunas.excluir(escopo, coluna_id)
    escopo.db.commit()
    return Response(status_code=204)
