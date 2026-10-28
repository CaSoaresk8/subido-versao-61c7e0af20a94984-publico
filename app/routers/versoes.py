from urllib.parse import urlsplit
import ipaddress
import json
import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select

from app.deps import escopo_logado, templates
from app.escopo import EscopoCla
from app.models import VersaoComunidade, ProjetoVersao


def habilitada():
    if os.environ.get("CENTRAL_ATIVA", "1") != "1":
        raise HTTPException(404)


router = APIRouter(prefix="/versoes", dependencies=[Depends(habilitada)])
CATEGORIAS = {
    "gestao": "Gestão do clã",
    "produtividade": "Produtividade",
    "automacao": "Automação",
    "aprendizado": "Aprendizado",
}


def _url(valor: str, obrigatorio: bool = False) -> str:
    valor = valor.strip()
    if not valor and not obrigatorio:
        return ""
    try:
        url = urlsplit(valor)
        host = url.hostname or ""
        if (
            len(valor) > 500
            or url.scheme != "https"
            or not host
            or url.username
            or url.password
            or url.port not in (None, 443)
        ):
            raise ValueError
        if host == "localhost" or "." not in host or host.endswith((".local", ".internal")):
            raise ValueError
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not ip.is_global:
                raise ValueError
    except ValueError:
        raise ValueError("Use um endereço HTTPS público, sem usuário ou senha na URL.") from None
    return valor


@router.get("")
def biblioteca(
    request: Request,
    q: str = "",
    categoria: str = "",
    minhas: bool = False,
    escopo: EscopoCla = Depends(escopo_logado),
):
    q = q.strip()[:100]
    stmt = select(VersaoComunidade)
    if q:
        termo = "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        stmt = stmt.where(
            or_(
                VersaoComunidade.nome.ilike(termo, escape="!"),
                VersaoComunidade.resumo.ilike(termo, escape="!"),
            )
        )
    if categoria in CATEGORIAS:
        stmt = stmt.where(VersaoComunidade.categoria == categoria)
    if minhas:
        stmt = stmt.where(VersaoComunidade.autor_id == escopo.membro.usuario_id)
    versoes = list(
        escopo.db.scalars(
            stmt.order_by(VersaoComunidade.criado_em.desc(), VersaoComunidade.id.desc())
        )
    )
    return templates.TemplateResponse(
        request,
        "versoes.html",
        {
            "membro": escopo.membro,
            "versoes": versoes,
            "categorias": CATEGORIAS,
            "q": q,
            "categoria": categoria,
            "minhas": minhas,
        },
    )


@router.get("/importar")
def nova(request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    return templates.TemplateResponse(
        request,
        "versao_form.html",
        {"membro": escopo.membro, "categorias": CATEGORIAS, "valores": {}, "erro": None},
    )


@router.post("/importar")
def publicar(
    request: Request,
    nome: str = Form(""),
    numero: str = Form(""),
    resumo: str = Form(""),
    novidades: str = Form(""),
    categoria: str = Form(""),
    repositorio: str = Form(""),
    demonstracao: str = Form(""),
    autor_publico: str = Form(""),
    confirmar: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    origem = request.headers.get("origin")
    if origem and origem != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Origem não autorizada")
    valores = {
        "nome": nome.strip(),
        "numero": numero.strip(),
        "resumo": resumo.strip(),
        "novidades": novidades.strip(),
        "categoria": categoria,
        "repositorio": repositorio.strip(),
        "demonstracao": demonstracao.strip(),
        "autor_publico": autor_publico.strip(),
    }
    try:
        for campo, limite in (
            ("nome", 100),
            ("numero", 40),
            ("resumo", 240),
            ("autor_publico", 80),
        ):
            if not valores[campo] or len(valores[campo]) > limite:
                raise ValueError(
                    "Preencha nome, versão, resumo e nome público dentro dos limites indicados."
                )
        if len(novidades) > 5000 or categoria not in CATEGORIAS:
            raise ValueError("Escolha uma categoria e limite as novidades a 5.000 caracteres.")
        if confirmar != "sim":
            raise ValueError("Confirme que deseja compartilhar esta versão com a comunidade.")
        valores["repositorio"] = _url(repositorio, obrigatorio=True)
        valores["demonstracao"] = _url(demonstracao)
    except ValueError as erro:
        return templates.TemplateResponse(
            request,
            "versao_form.html",
            {
                "membro": escopo.membro,
                "categorias": CATEGORIAS,
                "valores": valores,
                "erro": str(erro),
            },
            status_code=400,
        )
    versao = VersaoComunidade(**valores, autor_id=escopo.membro.usuario_id, exemplo=False)
    escopo.db.add(versao)
    escopo.db.commit()
    return RedirectResponse(f"/versoes/{versao.id}", status_code=303)


@router.get("/{versao_id}")
def detalhe(versao_id: int, request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    versao = escopo.db.get(VersaoComunidade, versao_id)
    if versao is None:
        raise HTTPException(404, "Versão não encontrada")
    integrada = any(
        (c := json.loads(p.configuracao)).get("biblioteca_id") == versao_id and c.get("vitrine_url")
        for p in escopo.db.scalars(select(ProjetoVersao))
    )
    return templates.TemplateResponse(
        request,
        "versao_detalhe.html",
        {
            "membro": escopo.membro,
            "versao": versao,
            "categorias": CATEGORIAS,
            "integrada": integrada,
        },
    )
