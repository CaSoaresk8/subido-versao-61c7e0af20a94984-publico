from fastapi import APIRouter, Depends, Request

from app.deps import escopo_logado, templates
from app.escopo import EscopoCla

router = APIRouter()
AULAS = (
    {
        "id": "8wL4UFu3EHo",
        "titulo": "Claude Code/Codex: do primeiro prompt ao sistema no ar",
        "tema": "Do primeiro prompt ao sistema no ar",
        "capa": "aula-ia-2-v2.webp",
        "estilo": "2",
    },
    {
        "id": "cMISpVp0a64",
        "titulo": "Gestão de tráfego com IA através do MCP do Meta",
        "tema": "Otimização de campanha com MCP do Meta",
        "capa": "aula-mcp-meta-v3.webp",
        "estilo": "2",
    },
)


@router.get("/aulas-ia")
def aulas_ia(request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    return templates.TemplateResponse(
        request, "aulas_ia.html", {"membro": escopo.membro, "aulas": AULAS}
    )
