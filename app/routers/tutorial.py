"""A tela do video que explica o app.

Publica de proposito, e nao atras do login. Ela aparece em dois lugares que sao os dois extremos
do funil: no menu de quem ja esta dentro, e na tela de criar cla, onde a pessoa ainda nao tem
conta nenhuma. Exigir sessao aqui quebraria o segundo caso, que e justamente o que mais precisa
de explicacao.

`membro_opcional` e o que faz o cabecalho aparecer inteiro para quem esta logado e sumir para quem
nao esta: ele passa por `escopo_opcional`, que poe o escopo em `request.state`, que e de onde o
context processor tira o nome do cla. Sem essa dependencia a pagina abriria do mesmo jeito, mas
quem estivesse logado veria a tela de visitante, sem menu para voltar.
"""

from fastapi import APIRouter, Depends, Request

from app.deps import membro_opcional, templates
from app.models import Membro

router = APIRouter()


@router.get("/tutorial")
def tela_tutorial(
    request: Request,
    membro: Membro | None = Depends(membro_opcional),
):
    return templates.TemplateResponse(request, "tutorial.html", {"membro": membro})
