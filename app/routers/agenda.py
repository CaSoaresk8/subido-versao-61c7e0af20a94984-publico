"""As telas da agenda do cla. A regra mora em `servicos/agenda.py`; aqui so entra o que e de tela.

O login do Google (conectar/retorno) so existe aqui, e nao na API: ele e um vai-e-volta de
navegador inteiro (a pessoa sai do app, autoriza no Google e volta), e isso nao se faz por fetch.
"""

import secrets
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import GOOGLE_CONFIGURADO
from app.deps import escopo_logado, templates
from app.escopo import EscopoCla
from app.models import TIPOS_DE_EVENTO, Evento
from app.repositorios import eventos as repo_eventos
from app.repositorios import membros as repo_membros
from app.repositorios import plataforma as repo_plataforma
from app.servicos import agenda as servico_agenda
from app.servicos import google_agenda
from app.servicos.calendario import MESES, eventos_do_cla, grade_do_mes
from app.servicos.erros import ForaDeRegra


def _agenda_ligada() -> None:
    """Com a agenda desligada (`AGENDA_ATIVA=0`), toda rota daqui responde como se nao existisse."""
    from app import config

    if not config.AGENDA_ATIVA:
        raise HTTPException(status_code=404, detail="Página não encontrada")


router = APIRouter(prefix="/agenda", dependencies=[Depends(_agenda_ligada)])

CHAVE_ESTADO = "google_oauth"


def _evento_ativo(escopo: EscopoCla, evento_id: int) -> Evento:
    """Do cla de quem olha e fora da lixeira, ou 404. Outro cla e id inexistente sao o mesmo 404."""
    evento = repo_eventos.por_id(escopo, evento_id)
    if evento is None or not evento.ativo:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    return evento


def _so_dono(escopo: EscopoCla) -> None:
    """A conta Google e da plataforma inteira: so o dono da plataforma conecta e troca.

    404, e nao 403, pelo mesmo motivo do resto do app: para quem nao e dono, esta tela nao existe.
    """
    if not servico_agenda.e_dono_da_plataforma(escopo.membro.usuario):
        raise HTTPException(status_code=404, detail="Página não encontrada")


def _retorno(request: Request) -> str:
    return str(request.url_for("google_retorno"))


def _conduz(texto: str) -> int | None:
    texto = (texto or "").strip()
    return int(texto) if texto.isdigit() else None


def _duracao(texto: str) -> int:
    texto = (texto or "").strip()
    return int(texto) if texto.isdigit() else 0


def _form(
    request: Request,
    escopo: EscopoCla,
    evento: Evento | None,
    erro: str | None = None,
    valores: dict | None = None,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        "evento_form.html",
        {
            "membro": escopo.membro,
            "evento": evento,
            "valores": valores or {},
            "membros": repo_membros.todos(escopo),
            "tipos": TIPOS_DE_EVENTO,
            "erro": erro,
        },
        status_code=status_code,
    )


# ---------------------------------------------------------------------------------------------
# Lista e conta Google
# ---------------------------------------------------------------------------------------------


@router.get("")
def listar(
    request: Request,
    google: str | None = None,
    ano: int | None = None,
    mes: int | None = None,
    escopo: EscopoCla = Depends(escopo_logado),
):
    hoje = date.today()
    ano, mes = ano or hoje.year, mes or hoje.month
    if not 2 <= ano <= 9998 or not 1 <= mes <= 12:
        ano, mes = hoje.year, hoje.month
    calendario = {
        "semanas": grade_do_mes(ano, mes, eventos_do_cla(escopo, [], escopo.membro_id, ano, mes)),
        "mes_nome": MESES[mes - 1], "ano": ano, "mes": mes,
        "mes_anterior": (ano - 1, 12) if mes == 1 else (ano, mes - 1),
        "mes_seguinte": (ano + 1, 1) if mes == 12 else (ano, mes + 1),
    }
    eventos = repo_eventos.ativos(escopo)
    agora = servico_agenda.agora_local()
    proximos = [e for e in eventos if servico_agenda.fim(e) >= agora]
    # Os passados mais recentes primeiro, e so os ultimos: a agenda e para o que vem.
    passados = [e for e in reversed(eventos) if servico_agenda.fim(e) < agora][:10]
    return templates.TemplateResponse(
        request,
        "agenda.html",
        {
            **calendario,
            "membro": escopo.membro,
            "proximos": proximos,
            "passados": passados,
            "integracao": repo_plataforma.integracao_google(escopo.db),
            "google_configurado": GOOGLE_CONFIGURADO,
            "e_dono": servico_agenda.e_dono_da_plataforma(escopo.membro.usuario),
            "aviso_google": google,
            # Lido uma vez e apagado: o motivo da falha e da volta do Google que acabou de acontecer,
            # e continuar aparecendo em toda visita depois faria parecer que ainda esta quebrado.
            "erro_google": request.session.pop("google_erro", None) if google == "erro" else None,
            "tipos": TIPOS_DE_EVENTO,
        },
    )


@router.get("/google/conectar")
def conectar(request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    _so_dono(escopo)
    if not GOOGLE_CONFIGURADO:
        return RedirectResponse("/agenda?google=nao-configurado", status_code=303)
    # O `state` amarra a volta do Google a ESTA sessao e a ESTA conta. Sem ele, qualquer um poderia
    # mandar ao dono um link de retorno com um codigo da propria conta Google, e a plataforma
    # passaria a mandar convites por uma conta de fora sem ninguem ter clicado em conectar.
    estado = secrets.token_urlsafe(32)
    request.session[CHAVE_ESTADO] = {"state": estado, "usuario_id": escopo.membro.usuario_id}
    return RedirectResponse(
        google_agenda.url_de_autorizacao(_retorno(request), estado), status_code=303
    )


@router.get("/google/retorno", name="google_retorno")
def retorno(
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
    escopo: EscopoCla = Depends(escopo_logado),
):
    _so_dono(escopo)
    guardado = request.session.pop(CHAVE_ESTADO, None) or {}
    if (
        not state
        or not secrets.compare_digest(state, guardado.get("state", ""))
        or guardado.get("usuario_id") != escopo.membro.usuario_id
    ):
        return RedirectResponse("/agenda?google=expirou", status_code=303)
    if error or not code:
        # "access_denied" e a pessoa clicando em Cancelar no Google: nao e erro, e desistencia.
        return RedirectResponse("/agenda?google=cancelado", status_code=303)
    try:
        email, refresh = google_agenda.trocar_codigo(code, _retorno(request))
    except google_agenda.ErroGoogle as erro:
        request.session["google_erro"] = str(erro)
        return RedirectResponse("/agenda?google=erro", status_code=303)
    servico_agenda.conectar(escopo.db, escopo.membro.usuario, email, refresh)
    escopo.db.commit()
    return RedirectResponse("/agenda?google=conectado", status_code=303)


@router.post("/google/desconectar")
def desconectar(escopo: EscopoCla = Depends(escopo_logado)):
    _so_dono(escopo)
    servico_agenda.desconectar(escopo.db)
    escopo.db.commit()
    return RedirectResponse("/agenda?google=desconectado", status_code=303)


# ---------------------------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------------------------


@router.get("/novo")
def form_novo(request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    return _form(request, escopo, None)


@router.post("/novo")
def criar(
    request: Request,
    titulo: str = Form(""),
    tipo: str = Form("reuniao"),
    inicio: str = Form(""),
    duracao_min: str = Form("60"),
    local: str = Form(""),
    conduzido_por_id: str = Form(""),
    descricao: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    valores = {
        "titulo": titulo,
        "tipo": tipo,
        "inicio": inicio,
        "duracao_min": duracao_min,
        "local": local,
        "conduzido_por_id": conduzido_por_id,
        "descricao": descricao,
    }
    try:
        evento = servico_agenda.criar(
            escopo,
            titulo=titulo,
            inicio=servico_agenda.ler_inicio(inicio),
            tipo=tipo,
            duracao_min=_duracao(duracao_min),
            descricao=descricao,
            local=local,
            conduzido_por_id=_conduz(conduzido_por_id),
        )
    except ForaDeRegra as recusa:
        escopo.db.rollback()
        return _form(request, escopo, None, str(recusa), valores, status_code=400)
    escopo.db.commit()
    return RedirectResponse(f"/agenda/{evento.id}", status_code=303)


@router.get("/{evento_id}")
def detalhe(evento_id: int, request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    evento = _evento_ativo(escopo, evento_id)
    return templates.TemplateResponse(
        request,
        "evento_detalhe.html",
        {
            "membro": escopo.membro,
            "evento": evento,
            "fim": servico_agenda.fim(evento),
            "passou": servico_agenda.ja_passou(evento),
            "tipos": TIPOS_DE_EVENTO,
            "integracao": repo_plataforma.integracao_google(escopo.db),
            "link_google": servico_agenda.link_google_agenda(evento),
        },
    )


@router.get("/{evento_id}/editar")
def form_editar(evento_id: int, request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    return _form(request, escopo, _evento_ativo(escopo, evento_id))


@router.post("/{evento_id}/editar")
def editar(
    evento_id: int,
    request: Request,
    titulo: str = Form(""),
    tipo: str = Form("reuniao"),
    inicio: str = Form(""),
    duracao_min: str = Form("60"),
    local: str = Form(""),
    conduzido_por_id: str = Form(""),
    descricao: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    evento = _evento_ativo(escopo, evento_id)
    valores = {
        "titulo": titulo,
        "tipo": tipo,
        "inicio": inicio,
        "duracao_min": duracao_min,
        "local": local,
        "conduzido_por_id": conduzido_por_id,
        "descricao": descricao,
    }
    try:
        servico_agenda.editar(
            escopo,
            evento,
            titulo=titulo,
            inicio=servico_agenda.ler_inicio(inicio),
            tipo=tipo,
            duracao_min=_duracao(duracao_min),
            descricao=descricao,
            local=local,
            conduzido_por_id=_conduz(conduzido_por_id),
        )
    except ForaDeRegra as recusa:
        escopo.db.rollback()
        return _form(request, escopo, evento, str(recusa), valores, status_code=400)
    escopo.db.commit()
    return RedirectResponse(f"/agenda/{evento.id}", status_code=303)


@router.post("/{evento_id}/excluir")
def excluir(evento_id: int, escopo: EscopoCla = Depends(escopo_logado)):
    servico_agenda.excluir(escopo, _evento_ativo(escopo, evento_id))
    escopo.db.commit()
    return RedirectResponse("/agenda", status_code=303)


@router.post("/{evento_id}/reenviar")
def reenviar(evento_id: int, escopo: EscopoCla = Depends(escopo_logado)):
    """O "tentar de novo" do convite que falhou. E so sincronizar outra vez: a funcao e idempotente."""
    evento = _evento_ativo(escopo, evento_id)
    servico_agenda.sincronizar(escopo, evento)
    escopo.db.commit()
    return RedirectResponse(f"/agenda/{evento.id}", status_code=303)
