"""Politica de privacidade e termos de uso.

Publicas e sem login, e nao por formalidade: o Google exige os dois endereços abertos para publicar
o app que manda os convites da agenda, e uma pagina atras de login nao serve para isso.

`membro_opcional` pelo mesmo motivo do tutorial: quem ja esta logado continua vendo o cabecalho.
"""

from fastapi import APIRouter, Depends, Request

from app.deps import membro_opcional, templates
from app.models import Membro

router = APIRouter()


@router.get("/privacidade")
def privacidade(request: Request, membro: Membro | None = Depends(membro_opcional)):
    return templates.TemplateResponse(request, "privacidade.html", {"membro": membro})


@router.get("/termos")
def termos(request: Request, membro: Membro | None = Depends(membro_opcional)):
    return templates.TemplateResponse(request, "termos.html", {"membro": membro})
