"""As telas de missao. A regra mora em `servicos/missoes.py`; aqui so entra o que e de tela.

O que sobrou neste arquivo depois da API aparecer e exatamente o que nao da para reaproveitar entre
HTML e JSON: qual template desenhar, com que codigo de resposta, e para onde redirecionar depois.
Criar, editar, excluir e salvar entrega sao os mesmos servicos que `app/api/v1/missoes.py` chama.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.deps import escopo_logado, templates
from app.escopo import EscopoCla
from app.models import CONCLUIDO, Membro, Missao
from app.repositorios import membros as repo_membros
from app.repositorios import missoes as repo_missoes
from app.servicos import missoes as servico_missoes
from app.servicos.erros import FaltaResposta, ForaDeRegra
from app.servicos.ranking import progresso_da_missao

router = APIRouter(prefix="/missoes")


def _missao_ativa(escopo: EscopoCla, missao_id: int) -> Missao:
    """A missao do cla de quem esta olhando, fora da lixeira, ou 404.

    Missao de outro cla cai no mesmo 404 de missao que nao existe: o repositorio devolve None
    porque a consulta nasce filtrada pelo cla. Um 403 aqui diria "existe, mas nao e do seu cla",
    e isso e exatamente o que alguem varrendo ids quer saber.
    """
    missao = repo_missoes.por_id(escopo, missao_id)
    if missao is None or not missao.ativa:
        raise HTTPException(status_code=404, detail="Missão não encontrada")
    return missao


@router.get("")
def listar(
    request: Request,
    escopo: EscopoCla = Depends(escopo_logado),
):
    total_membros = repo_membros.total(escopo)
    missoes = [
        {"missao": missao, "progresso": progresso_da_missao(missao, total_membros)}
        for missao in repo_missoes.ativas(escopo, com_entregas=True)
    ]
    return templates.TemplateResponse(
        request, "missoes.html", {"membro": escopo.membro, "missoes": missoes}
    )


@router.get("/nova")
def form_nova(request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    return templates.TemplateResponse(
        request, "missao_form.html", {"membro": escopo.membro, "missao": None, "erro": None}
    )


@router.post("/nova")
def criar(
    request: Request,
    titulo: str = Form(...),
    descricao: str = Form(""),
    pontos: int = Form(0),
    vencimento: str = Form(""),
    exige_resposta: str = Form(""),
    rotulo_resposta: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    try:
        missao = servico_missoes.criar(
            escopo,
            titulo=titulo,
            descricao=descricao,
            pontos=pontos,
            vencimento=servico_missoes.data_da_missao(vencimento),
            exige_resposta=bool(exige_resposta),
            rotulo_resposta=rotulo_resposta,
        )
    except ForaDeRegra as recusa:
        return templates.TemplateResponse(
            request,
            "missao_form.html",
            {"membro": escopo.membro, "missao": None, "erro": str(recusa)},
            status_code=400,
        )
    escopo.db.commit()
    return RedirectResponse(f"/missoes/{missao.id}", status_code=303)


def _pagina_detalhe(
    request: Request,
    escopo: EscopoCla,
    missao: Missao,
    erro: str | None = None,
    status_code: int = 200,
):
    membro: Membro = escopo.membro
    total_membros = repo_membros.total(escopo)
    minha = next((e for e in missao.entregas if e.membro_id == membro.id), None)
    entregas = sorted(missao.entregas, key=lambda e: (e.status != CONCLUIDO, e.membro.nome))
    return templates.TemplateResponse(
        request,
        "missao_detalhe.html",
        {
            "membro": membro,
            "missao": missao,
            "minha": minha,
            "entregas": entregas,
            "progresso": progresso_da_missao(missao, total_membros),
            "rotulo_resposta": servico_missoes.rotulo_da_resposta(missao),
            "erro": erro,
        },
        status_code=status_code,
    )


@router.get("/{missao_id}")
def detalhe(
    missao_id: int,
    request: Request,
    erro: str | None = None,
    escopo: EscopoCla = Depends(escopo_logado),
):
    missao = _missao_ativa(escopo, missao_id)
    return _pagina_detalhe(request, escopo, missao, erro="resposta" if erro else None)


@router.get("/{missao_id}/editar")
def form_editar(
    missao_id: int,
    request: Request,
    escopo: EscopoCla = Depends(escopo_logado),
):
    missao = _missao_ativa(escopo, missao_id)
    return templates.TemplateResponse(
        request, "missao_form.html", {"membro": escopo.membro, "missao": missao, "erro": None}
    )


@router.post("/{missao_id}/editar")
def editar(
    missao_id: int,
    titulo: str = Form(...),
    descricao: str = Form(""),
    pontos: int = Form(0),
    vencimento: str = Form(""),
    exige_resposta: str = Form(""),
    rotulo_resposta: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    missao = _missao_ativa(escopo, missao_id)
    servico_missoes.editar(
        escopo,
        missao,
        titulo=titulo,
        descricao=descricao,
        pontos=pontos,
        vencimento=servico_missoes.data_da_missao(vencimento),
        exige_resposta=bool(exige_resposta),
        rotulo_resposta=rotulo_resposta,
    )
    escopo.db.commit()
    return RedirectResponse(f"/missoes/{missao.id}", status_code=303)


@router.post("/{missao_id}/excluir")
def excluir(
    missao_id: int,
    escopo: EscopoCla = Depends(escopo_logado),
):
    missao = _missao_ativa(escopo, missao_id)
    servico_missoes.excluir(escopo, missao)
    escopo.db.commit()
    return RedirectResponse("/historico", status_code=303)


@router.post("/{missao_id}/entrega")
def atualizar_entrega(
    missao_id: int,
    request: Request,
    status: str = Form(...),
    resposta: str = Form(""),
    observacao: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    missao = _missao_ativa(escopo, missao_id)
    try:
        servico_missoes.salvar_entrega(escopo, missao, status, resposta, observacao)
    except ForaDeRegra as recusa:
        raise HTTPException(status_code=400, detail=str(recusa)) from recusa
    except FaltaResposta:
        # O servico ja escreveu na entrega antes de descobrir que o campo estava vazio. Sem o
        # rollback, a resposta em branco ficaria gravada junto com o status antigo.
        escopo.db.rollback()
        return _pagina_detalhe(request, escopo, missao, erro="resposta", status_code=400)
    escopo.db.commit()
    return RedirectResponse(f"/missoes/{missao.id}", status_code=303)
