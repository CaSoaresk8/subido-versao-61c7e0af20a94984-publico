"""Junta os routers da versao 1 da API sob /api/v1.

A versao esta no caminho, e nao num header, porque o caminho e o que aparece no log, no teste e na
barra do navegador quando algo da errado. Quando existir uma v2, as duas convivem como dois
prefixos, e o dia de apagar a v1 e o dia em que ninguem mais a chama.
"""

from fastapi import APIRouter

from app.api.v1 import (
    agenda,
    clas,
    colunas,
    convites,
    historico,
    membros,
    missoes,
    painel,
    quadro,
    saude,
    sessao,
    tarefas,
)

router = APIRouter(prefix="/api/v1")

# `saude` primeiro porque ele e o unico que nao depende de nada: se a importacao de qualquer outro
# quebrar, isso aparece no boot e nao numa chamada de madrugada.
for parte in (
    saude,
    sessao,
    clas,
    convites,
    membros,
    missoes,
    agenda,
    tarefas,
    colunas,
    quadro,
    painel,
    historico,
):
    router.include_router(parte.router)
