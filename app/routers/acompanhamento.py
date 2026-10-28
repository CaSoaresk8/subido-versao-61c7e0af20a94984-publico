"""As telas do acompanhamento semanal. A regra mora em `servicos/acompanhamento.py`."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.deps import escopo_logado, templates
from app.escopo import EscopoCla
from app.models import STATUS_DO_DIARIO, Membro
from app.repositorios import diario as repo
from app.repositorios import membros as repo_membros
from app.servicos import acompanhamento as servico
from app.servicos.erros import ForaDeRegra, NaoEncontrado

router = APIRouter(prefix="/acompanhamento")


def _pessoa(escopo: EscopoCla, membro_id: int) -> Membro:
    pessoa = escopo.obter(Membro, membro_id)
    if pessoa is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    return pessoa


def _volta(destino: str, erro: str | None = None) -> RedirectResponse:
    return RedirectResponse(destino + (f"?erro={quote(erro)}" if erro else ""), status_code=303)



def _foco(escopo: EscopoCla, alvo: Membro, resumo: dict) -> dict:
    from datetime import timedelta

    detalhes = servico.pode_ver_detalhes(escopo, alvo.id)
    historico = repo.historico_da_pessoa(escopo, alvo.id)
    por_semana = {e.semana: e for e in historico}
    inicio = min(por_semana, default=resumo["semana"])
    semanas = []
    cursor = inicio
    while cursor <= resumo["semana"]:
        semanas.append({"semana": cursor, "entrada": por_semana.get(cursor)})
        cursor += timedelta(days=7)
    return {
        "pessoa": alvo,
        "detalhes": detalhes,
        "perfil": repo.perfil(escopo, alvo.id) if detalhes else None,
        "historico": historico,
        "semanas_historico": semanas,
        "desta_semana": resumo["entradas"].get(alvo.id),
        "pode_registrar": resumo["sou_responsavel"] and alvo.id != escopo.membro_id,
        "pode_editar_perfil": detalhes,
    }


@router.get("")
def semana(
    request: Request,
    erro: str | None = None,
    pessoa_id: int | None = None,
    escopo: EscopoCla = Depends(escopo_logado),
):
    resumo = servico.resumo_da_semana(escopo)
    ultimas = repo.ultimas_entradas(escopo)
    membros = repo_membros.todos(escopo)
    alvo = _pessoa(escopo, pessoa_id) if pessoa_id is not None else (membros[0] if membros else None)
    return templates.TemplateResponse(
        request,
        "acompanhamento.html",
        {
            "membro": escopo.membro,
            "resumo": resumo,
            "membros": membros,
            **(_foco(escopo, alvo, resumo) if alvo else {}),
            "ultimas": ultimas,
            "status_do_diario": STATUS_DO_DIARIO,
            "erro": erro,
        },
    )


@router.post("/assumir")
def assumir(escopo: EscopoCla = Depends(escopo_logado)):
    try:
        servico.assumir(escopo)
    except ForaDeRegra as recusa:
        escopo.db.rollback()
        return _volta("/acompanhamento", str(recusa))
    escopo.db.commit()
    return _volta("/acompanhamento")


@router.post("/transferir")
def transferir(para: int = Form(...), escopo: EscopoCla = Depends(escopo_logado)):
    try:
        servico.transferir(escopo, para)
    except ForaDeRegra as recusa:
        escopo.db.rollback()
        return _volta("/acompanhamento", str(recusa))
    escopo.db.commit()
    return _volta("/acompanhamento")


@router.get("/{membro_id}")
def pessoa(
    membro_id: int,
    request: Request,
    erro: str | None = None,
    escopo: EscopoCla = Depends(escopo_logado),
):
    alvo = _pessoa(escopo, membro_id)
    resumo = servico.resumo_da_semana(escopo)
    return templates.TemplateResponse(
        request,
        "acompanhamento.html",
        {
            "membro": escopo.membro,
            "membros": repo_membros.todos(escopo),
            "ultimas": repo.ultimas_entradas(escopo),
            "resumo": resumo,
            "status_do_diario": STATUS_DO_DIARIO,
            "erro": erro,
            **_foco(escopo, alvo, resumo),
        },
    )


@router.post("/{membro_id}/conversa")
def registrar_conversa(
    membro_id: int,
    status: str = Form(...),
    como_esta: str = Form(""),
    combinados: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    alvo = _pessoa(escopo, membro_id)
    try:
        servico.registrar_conversa(escopo, alvo, status, como_esta, combinados)
    except ForaDeRegra as recusa:
        escopo.db.rollback()
        return _volta(f"/acompanhamento/{membro_id}", str(recusa))
    escopo.db.commit()
    return _volta(f"/acompanhamento/{membro_id}")


@router.post("/{membro_id}/perfil")
def salvar_perfil(
    membro_id: int,
    sobre: str = Form(""),
    metas: str = Form(""),
    dificuldades: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    alvo = _pessoa(escopo, membro_id)
    try:
        servico.salvar_perfil(escopo, alvo, sobre, metas, dificuldades)
    except NaoEncontrado:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada") from None
    except ForaDeRegra as recusa:
        escopo.db.rollback()
        return _volta(f"/acompanhamento/{membro_id}", str(recusa))
    escopo.db.commit()
    return _volta(f"/acompanhamento/{membro_id}")
