import json
import os
import re
import secrets
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import select

from app.deps import escopo_logado, templates
from app.escopo import EscopoCla
from app.models import ConexaoCentral, ProjetoVersao, TarefaCentral, VersaoComunidade
from app.servicos.central import codigo, cofre, fluxo, provedores


def habilitada():
    if os.environ.get("CENTRAL_ATIVA", "1") != "1":
        raise HTTPException(404)


router = APIRouter(prefix="/versoes", dependencies=[Depends(habilitada)])


def origem(request):
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        request.headers.get("origin")
        and request.headers["origin"] != str(request.base_url).rstrip("/")
    ):
        raise HTTPException(403, "Origem não autorizada")


def projeto(escopo, pid):
    p = escopo.db.scalar(
        select(ProjetoVersao).where(
            ProjetoVersao.id == pid, ProjetoVersao.autor_id == escopo.membro.usuario_id
        )
    )
    if p is None:
        raise HTTPException(404, "Projeto não encontrado")
    return p


def render(request, escopo, template, **dados):
    return templates.TemplateResponse(request, template, {"membro": escopo.membro, **dados})


def voltar(pid, erro=None):
    from urllib.parse import urlencode

    return RedirectResponse(
        "/versoes/projetos/" + pid + ("?" + urlencode({"erro": erro}) if erro else ""),
        status_code=303,
    )


@router.get("/criar")
def criar_tela(
    request: Request, base: int | None = None, escopo: EscopoCla = Depends(escopo_logado)
):
    bases = list(
        escopo.db.scalars(select(VersaoComunidade).where(VersaoComunidade.exemplo.is_(False)))
    )
    return render(request, escopo, "central_criar.html", bases=bases, base=base, erro=None)


@router.post("/criar")
def criar(
    request: Request,
    nome: str = Form(""),
    base: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    origem(request)
    if not 2 <= len(nome.strip()) <= 100:
        raise HTTPException(400, "Informe um nome entre 2 e 100 caracteres")
    base_id = int(base) if base.isdigit() else None
    base_projeto = None
    base_sha = None
    if base_id is not None:
        v = escopo.db.get(VersaoComunidade, base_id)
        if v is None or v.exemplo:
            raise HTTPException(400, "Esta ficha não tem uma versão de código disponível.")
        for p in escopo.db.scalars(select(ProjetoVersao)):
            if json.loads(p.configuracao).get("biblioteca_id") == base_id:
                base_projeto = p.id
                base_sha = json.loads(p.configuracao).get("publicado_sha")
                break
        if not base_projeto and v.repositorio != "https://github.com/CaSoaresk8/copy-e-cola":
            raise HTTPException(
                400,
                "Importe o pacote de código desta versão; o registro externo não possui uma cópia na central.",
            )
    p = ProjetoVersao(
        id=uuid.uuid4().hex,
        autor_id=escopo.membro.usuario_id,
        nome=nome.strip(),
        base_id=base_id,
        estado="criando",
        configuracao="{}",
    )
    escopo.db.add(p)
    escopo.db.commit()
    fluxo.enfileirar(escopo.db, p, "criar", {"base_projeto": base_projeto, "base_sha": base_sha})
    return voltar(p.id)


@router.get("/projetos")
def meus_projetos(request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    projetos = list(
        escopo.db.scalars(
            select(ProjetoVersao)
            .where(ProjetoVersao.autor_id == escopo.membro.usuario_id)
            .order_by(ProjetoVersao.criado_em.desc())
        )
    )
    return render(request, escopo, "central_projetos.html", projetos=projetos)


@router.get("/conexoes")
def conexoes(request: Request, erro: str = "", escopo: EscopoCla = Depends(escopo_logado)):
    lista = list(
        escopo.db.scalars(
            select(ConexaoCentral).where(ConexaoCentral.autor_id == escopo.membro.usuario_id)
        )
    )
    return render(request, escopo, "central_conexoes.html", conexoes=lista, erro=erro)


@router.post("/conexoes")
def conectar(
    request: Request,
    provedor: str = Form(...),
    token: str = Form(...),
    organizacao: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    origem(request)
    credencial = cofre.Credencial(token=token)
    try:
        cifrado = cofre.cifrar(credencial)
        identidade = provedores.validar_conexao(provedor, credencial.token, organizacao.strip())
        c = escopo.db.scalar(
            select(ConexaoCentral).where(
                ConexaoCentral.autor_id == escopo.membro.usuario_id,
                ConexaoCentral.provedor == provedor,
            )
        )
        if c is None:
            c = ConexaoCentral(autor_id=escopo.membro.usuario_id, provedor=provedor)
            escopo.db.add(c)
        c.token_cifrado = cifrado
        c.identidade = identidade
        escopo.db.commit()
    except ValueError as e:
        return render(
            request,
            escopo,
            "central_conexoes.html",
            conexoes=list(
                escopo.db.scalars(
                    select(ConexaoCentral).where(
                        ConexaoCentral.autor_id == escopo.membro.usuario_id
                    )
                )
            ),
            erro=str(e),
        )
    return RedirectResponse("/versoes/conexoes", status_code=303)


@router.post("/conexoes/{cid}/desconectar")
def desconectar(cid: int, request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    origem(request)
    c = escopo.db.scalar(
        select(ConexaoCentral).where(
            ConexaoCentral.id == cid, ConexaoCentral.autor_id == escopo.membro.usuario_id
        )
    )
    if c is None:
        raise HTTPException(404)
    escopo.db.delete(c)
    escopo.db.commit()
    return RedirectResponse("/versoes/conexoes", status_code=303)


@router.get("/projetos/{pid}")
def painel(
    pid: str,
    request: Request,
    arquivo: str = "app/templates/dashboard.html",
    erro: str = "",
    escopo: EscopoCla = Depends(escopo_logado),
):
    p = projeto(escopo, pid)
    pronto = codigo.pasta(pid).joinpath(".git").exists()
    files = codigo.arquivos(pid) if pronto else []
    texto = ""
    if arquivo in files:
        try:
            texto = (codigo.pasta(pid) / arquivo).read_text()
        except (UnicodeError, OSError):
            arquivo = ""
    config = fluxo.configuracao(p)
    publicos = {k: v for k, v in config.items() if not k.endswith("_key")}
    tarefas = list(
        escopo.db.scalars(
            select(TarefaCentral)
            .where(TarefaCentral.projeto_id == pid, TarefaCentral.autor_id == p.autor_id)
            .order_by(TarefaCentral.criado_em.desc())
            .limit(20)
        )
    )
    return render(
        request,
        escopo,
        "central_painel.html",
        projeto=p,
        config=publicos,
        arquivos=files,
        arquivo=arquivo,
        texto=texto,
        historico=codigo.historico(pid) if pronto else [],
        tarefas=tarefas,
        ocupada=fluxo.ocupada(escopo.db, pid),
        erro=erro,
        pronto=pronto,
    )


@router.post("/projetos/{pid}/editar")
def editar(
    pid: str,
    request: Request,
    arquivo: str = Form(...),
    texto: str = Form(...),
    escopo: EscopoCla = Depends(escopo_logado),
):
    origem(request)
    p = projeto(escopo, pid)
    try:
        if fluxo.ocupada(escopo.db, pid):
            raise ValueError("Aguarde a tarefa atual antes de editar.")
        codigo.editar(pid, arquivo, texto)
        p.estado = "rascunho"
        escopo.db.commit()
    except ValueError as e:
        return voltar(pid, str(e))
    return voltar(pid)


@router.post("/projetos/{pid}/importar")
async def importar(
    pid: str,
    request: Request,
    pacote: UploadFile = File(...),
    escopo: EscopoCla = Depends(escopo_logado),
):
    origem(request)
    p = projeto(escopo, pid)
    try:
        if fluxo.ocupada(escopo.db, pid):
            raise ValueError("Aguarde a tarefa atual antes de importar.")
        conteudo = await pacote.read(codigo.MAX_TOTAL + 1)
        codigo.importar(pid, conteudo)
        p.estado = "rascunho"
        escopo.db.commit()
    except ValueError as e:
        return voltar(pid, str(e))
    return voltar(pid)


@router.get("/projetos/{pid}/codigo.zip")
def baixar(pid: str, escopo: EscopoCla = Depends(escopo_logado)):
    projeto(escopo, pid)
    if not (codigo.pasta(pid) / ".git").is_dir():
        raise HTTPException(409, "Aguarde a criação do código.")
    return Response(
        codigo.exportar(pid),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="minha-versao.zip"'},
    )


@router.post("/projetos/{pid}/acao")
def acao(
    pid: str,
    request: Request,
    acao: str = Form(...),
    confirmar: str = Form(""),
    numero: str = Form(""),
    resumo: str = Form(""),
    novidades: str = Form(""),
    categoria: str = Form("gestao"),
    autor_publico: str = Form(""),
    host: str = Form(""),
    titulo: str = Form(""),
    descricao: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    origem(request)
    p = projeto(escopo, pid)
    permitidas = {
        "conferir",
        "sincronizar",
        "previa",
        "publicar",
        "propor",
        "dominio",
        "verificar_dominio",
    }
    if acao not in permitidas:
        raise HTTPException(400, "Ação inválida")
    dados = {}
    try:
        if acao != "conferir" and confirmar != "sim":
            raise ValueError("Revise e confirme esta ação antes de continuar.")
        if acao == "publicar":
            if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?", numero):
                raise ValueError("Use um número de versão como 1.0.0.")
            if (
                not 1 <= len(resumo.strip()) <= 240
                or not 1 <= len(autor_publico.strip()) <= 80
                or len(novidades) > 5000
                or categoria not in {"gestao", "produtividade", "automacao", "aprendizado"}
            ):
                raise ValueError("Revise descrição, categoria e nome público.")
            dados = dict(
                numero=numero,
                resumo=resumo.strip(),
                novidades=novidades.strip(),
                categoria=categoria,
                autor_publico=autor_publico.strip(),
            )
        if acao in ("dominio", "verificar_dominio"):
            if not re.fullmatch(
                r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
                host.lower().strip(),
            ):
                raise ValueError("Informe somente o domínio, sem protocolo ou caminho.")
            dados = {"host": host.lower().strip()}
        if acao == "propor":
            if not 3 <= len(titulo.strip()) <= 150 or not 10 <= len(descricao.strip()) <= 5000:
                raise ValueError("Descreva o título e o benefício da proposta.")
            dados = {"titulo": titulo.strip(), "descricao": descricao.strip()}
        fluxo.enfileirar(escopo.db, p, acao, dados)
    except ValueError as e:
        return voltar(pid, str(e))
    return voltar(pid)


@router.get("/projetos/{pid}/estado")
def estado(pid: str, escopo: EscopoCla = Depends(escopo_logado)):
    p = projeto(escopo, pid)
    tarefas = list(
        escopo.db.scalars(
            select(TarefaCentral)
            .where(TarefaCentral.projeto_id == pid, TarefaCentral.autor_id == p.autor_id)
            .order_by(TarefaCentral.criado_em.desc())
            .limit(10)
        )
    )
    return {
        "estado": p.estado,
        "ocupada": fluxo.ocupada(escopo.db, pid),
        "tarefas": [{"acao": t.acao, "estado": t.estado, "mensagem": t.mensagem} for t in tarefas],
    }


@router.get("/projetos/{pid}/experimentar", response_class=HTMLResponse)
def experimentar(pid: str, request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    p = projeto(escopo, pid)
    config = fluxo.configuracao(p)
    if not config.get("previa_url") or not config.get("previa_key"):
        raise HTTPException(400, "Prepare a prévia antes de abrir a demonstração.")
    codigo_acesso = URLSafeTimedSerializer(config["previa_key"], salt="subido-demo").dumps(
        {"aud": pid, "nonce": secrets.token_hex(32)}
    )
    return render(
        request,
        escopo,
        "central_entrar_demo.html",
        destino=config["previa_url"] + "/demonstracao/entrar",
        codigo=codigo_acesso,
    )


@router.get("/{vid}/experimentar", response_class=HTMLResponse)
def experimentar_publica(vid: int, request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    v = escopo.db.get(VersaoComunidade, vid)
    if not v or v.exemplo:
        raise HTTPException(404)
    for p in escopo.db.scalars(select(ProjetoVersao)):
        c = fluxo.configuracao(p)
        if c.get("biblioteca_id") == vid and c.get("vitrine_url") and c.get("vitrine_key"):
            acesso = URLSafeTimedSerializer(c["vitrine_key"], salt="subido-demo").dumps(
                {"aud": p.id, "nonce": secrets.token_hex(32)}
            )
            return render(
                request,
                escopo,
                "central_entrar_demo.html",
                destino=c["vitrine_url"] + "/demonstracao/entrar",
                codigo=acesso,
            )
    raise HTTPException(400, "Esta versão externa não oferece acesso integrado à demonstração.")
