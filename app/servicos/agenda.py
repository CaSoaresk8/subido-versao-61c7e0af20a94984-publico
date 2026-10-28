"""Regra da agenda do cla: reunioes, workshops e o convite que sai pelo Google Agenda.

Como em `servicos/missoes.py`, as funcoes de escrita escrevem, anotam no log e **nao dao commit**:
a mesma regra e chamada pela tela e pela API, e quem chamou decide se a operacao inteira vale.

A regra mais importante daqui: **o Google nunca derruba o app.** Salvar um evento e uma coisa,
mandar o convite e outra. Se o Google estiver fora, se a conta tiver tirado a permissao, ou se
ninguem conectou conta nenhuma, o evento continua salvo e aparece para o cla inteiro; o que muda e
`google_status`, que a tela mostra como "convite nao enviado" com o motivo e um botao de tentar de
novo. Um cla sem Google conectado usa a agenda do mesmo jeito, so sem o email.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import DONOS_DA_PLATAFORMA, FUSO, URL_PUBLICA
from app.escopo import EscopoCla
from app.models import (
    CONVITE_ENVIADO,
    CONVITE_ERRO,
    TIPOS_DE_EVENTO,
    Evento,
    IntegracaoGoogle,
    Membro,
    Usuario,
    agora,
)
from app.repositorios import eventos as repo_eventos
from app.repositorios import plataforma as repo_plataforma
from app.servicos import google_agenda
from app.servicos.auditoria import registrar
from app.servicos.erros import ForaDeRegra, NaoEncontrado

log = logging.getLogger(__name__)

MINIMO_TITULO = 3
DURACAO_MINIMA = 15
DURACAO_MAXIMA = 12 * 60
MAXIMO_LOCAL = 500


def agora_local() -> datetime:
    """Hora de parede em Brasilia, sem tzinfo: o mesmo tipo de `Evento.inicio`."""
    return datetime.now(ZoneInfo(FUSO)).replace(tzinfo=None)


def fim(evento: Evento) -> datetime:
    return evento.inicio + timedelta(minutes=evento.duracao_min)


def ja_passou(evento: Evento) -> bool:
    return fim(evento) < agora_local()


# ---------------------------------------------------------------------------------------------
# Validacao
# ---------------------------------------------------------------------------------------------


def ler_inicio(texto: str | None) -> datetime:
    """O `datetime-local` do formulario ("2026-09-25T20:00"). Vazio ou torto vira ForaDeRegra."""
    texto = (texto or "").strip()
    if not texto:
        raise ForaDeRegra("Escolha o dia e a hora do evento.")
    try:
        inicio = datetime.fromisoformat(texto)
    except ValueError as erro:
        raise ForaDeRegra("A data e a hora do evento não estão num formato válido.") from erro
    # Segundos e tzinfo nao existem no formulario; se vierem pela API, sao descartados em vez de
    # virarem um evento as 20:00:37 que o Google mostra como 20:00 e o app como outra coisa.
    return inicio.replace(second=0, microsecond=0, tzinfo=None)


def _validar(
    escopo: EscopoCla,
    titulo: str,
    tipo: str,
    duracao_min: int,
    local: str,
    conduzido_por_id: int | None,
) -> None:
    if len(titulo.strip()) < MINIMO_TITULO:
        raise ForaDeRegra("Escreva um título para o evento.")
    if tipo not in TIPOS_DE_EVENTO:
        raise ForaDeRegra("Escolha o tipo do evento.")
    if not DURACAO_MINIMA <= duracao_min <= DURACAO_MAXIMA:
        raise ForaDeRegra(f"A duração vai de {DURACAO_MINIMA} minutos a 12 horas.")
    if len(local) > MAXIMO_LOCAL:
        raise ForaDeRegra("O link ou endereço ficou comprido demais.")
    if conduzido_por_id is not None and escopo.obter(Membro, conduzido_por_id) is None:
        # Membro de outro cla cai aqui tambem, e com a mesma frase: a FK composta recusaria de
        # qualquer jeito, mas com um erro de banco em vez de uma frase que a pessoa entende.
        raise ForaDeRegra("Quem conduz precisa ser alguém do clã.")


# ---------------------------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------------------------


def criar(
    escopo: EscopoCla,
    titulo: str,
    inicio: datetime,
    tipo: str = "reuniao",
    duracao_min: int = 60,
    descricao: str = "",
    local: str = "",
    conduzido_por_id: int | None = None,
) -> Evento:
    """Cria o evento, anota no log e tenta mandar o convite. Nao da commit."""
    _validar(escopo, titulo, tipo, duracao_min, local.strip(), conduzido_por_id)
    evento = Evento(
        cla_id=escopo.cla_id,
        titulo=titulo.strip(),
        tipo=tipo,
        descricao=descricao.strip(),
        inicio=inicio,
        duracao_min=duracao_min,
        local=local.strip(),
        conduzido_por_id=conduzido_por_id,
        criado_por_id=escopo.membro_id,
    )
    escopo.db.add(evento)
    escopo.db.flush()
    registrar(escopo, "criou", "evento", evento.id, evento.titulo)
    sincronizar(escopo, evento)
    return evento


def editar(
    escopo: EscopoCla,
    evento: Evento,
    titulo: str,
    inicio: datetime,
    tipo: str = "reuniao",
    duracao_min: int = 60,
    descricao: str = "",
    local: str = "",
    conduzido_por_id: int | None = None,
) -> Evento:
    """Edita e atualiza o MESMO convite no Google, que avisa os convidados da mudanca."""
    _validar(escopo, titulo, tipo, duracao_min, local.strip(), conduzido_por_id)
    evento.titulo = titulo.strip()
    evento.tipo = tipo
    evento.descricao = descricao.strip()
    evento.inicio = inicio
    evento.duracao_min = duracao_min
    evento.local = local.strip()
    evento.conduzido_por_id = conduzido_por_id
    escopo.db.flush()
    registrar(escopo, "editou", "evento", evento.id, evento.titulo)
    sincronizar(escopo, evento)
    return evento


def excluir(escopo: EscopoCla, evento: Evento) -> None:
    """Vai para a lixeira, como tudo no app, e o convite e cancelado para todo mundo."""
    evento.excluido_em = agora()
    evento.excluido_por_id = escopo.membro_id
    registrar(escopo, "excluiu", "evento", evento.id, evento.titulo)
    sincronizar(escopo, evento)


def restaurar(escopo: EscopoCla, evento: Evento) -> None:
    if evento.ativo:
        raise NaoEncontrado("Evento não encontrado na lixeira")
    evento.excluido_em = None
    evento.excluido_por_id = None
    registrar(escopo, "restaurou", "evento", evento.id, evento.titulo)
    sincronizar(escopo, evento)


# ---------------------------------------------------------------------------------------------
# O convite no Google
# ---------------------------------------------------------------------------------------------


def corpo_do_convite(escopo: EscopoCla, evento: Evento, email_de_quem_envia: str) -> dict:
    """O evento no formato da API do Google Agenda.

    `guestsCanSeeOtherGuests: False` e a linha que importa para LGPD: sem ela, cada convidado ve o
    email de cadastro de todos os outros membros na lista do convite. No app ninguem ve o email de
    ninguem, e o convite nao pode ser a porta dos fundos disso.
    """
    tipo = TIPOS_DE_EVENTO.get(evento.tipo, "Evento")
    linhas = [f"{tipo} do clã {escopo.cla.nome}."]
    if evento.conduzido_por is not None:
        linhas.append(f"Conduzido por {evento.conduzido_por.nome}.")
    if evento.descricao:
        linhas += ["", evento.descricao]
    if URL_PUBLICA:
        linhas += ["", f"No app: {URL_PUBLICA}/agenda/{evento.id}"]
    convidados = [
        {"email": email}
        for email in repo_eventos.emails_dos_membros(escopo)
        if email.lower() != email_de_quem_envia.lower()
    ]
    return {
        "summary": evento.titulo,
        "description": "\n".join(linhas),
        "location": evento.local,
        "start": {"dateTime": evento.inicio.isoformat(timespec="minutes"), "timeZone": FUSO},
        "end": {"dateTime": fim(evento).isoformat(timespec="minutes"), "timeZone": FUSO},
        "attendees": convidados,
        "guestsCanSeeOtherGuests": False,
        "guestsCanInviteOthers": False,
        "reminders": {"useDefault": True},
    }


def sincronizar(escopo: EscopoCla, evento: Evento) -> None:
    """Deixa o Google igual ao app para este evento. Nunca levanta: o resultado vai para o evento.

    Idempotente de proposito, e e isso que deixa o "tentar de novo" ser so chamar esta funcao outra
    vez: evento ativo com id no Google e atualizado, sem id e criado, excluido e cancelado.
    """
    integracao = repo_plataforma.integracao_google(escopo.db)
    if integracao is None:
        evento.google_status = ""
        evento.google_erro = ""
        return
    try:
        refresh = google_agenda.decifrar(integracao.token_cifrado)
        if not evento.ativo:
            if evento.google_evento_id:
                google_agenda.cancelar_evento(refresh, evento.google_evento_id)
            evento.google_status = ""
            evento.google_erro = ""
            return
        corpo = corpo_do_convite(escopo, evento, integracao.email)
        if evento.google_evento_id:
            evento.google_evento_id = google_agenda.atualizar_evento(
                refresh, evento.google_evento_id, corpo
            )
        else:
            evento.google_evento_id = google_agenda.criar_evento(refresh, corpo)
        evento.google_status = CONVITE_ENVIADO
        evento.google_erro = ""
    except google_agenda.ErroGoogle as erro:
        # Sem email, sem titulo: o log do servidor so precisa do id para achar o evento.
        log.warning("convite do evento %s nao sincronizou: %s", evento.id, erro)
        evento.google_status = CONVITE_ERRO
        evento.google_erro = str(erro)


def sincronizar_futuros(escopo: EscopoCla) -> None:
    """Todo evento que ainda vai acontecer. Serve para quem acabou de entrar e para a conta nova."""
    for evento in repo_eventos.futuros(escopo, agora_local()):
        sincronizar(escopo, evento)


def convidar_quem_entrou(escopo: EscopoCla) -> None:
    """Chamado quando alguem entra no cla: passa a estar nos convites do que ainda vai acontecer.

    Engole qualquer falha, e nao so do Google: entrar no cla e o que a pessoa veio fazer, e um
    problema no convite de uma reuniao nao pode transformar o link de convite em tela de erro.
    """
    if repo_plataforma.integracao_google(escopo.db) is None:
        return
    try:
        sincronizar_futuros(escopo)
    except Exception:  # noqa: BLE001
        log.exception("falha ao convidar membro novo para os eventos do cla %s", escopo.cla_id)


def e_dono_da_plataforma(usuario: Usuario) -> bool:
    return usuario.email.lower() in DONOS_DA_PLATAFORMA


def sincronizar_todos(db: Session) -> None:
    """Todo evento futuro de todo cla, cada um com o escopo do PROPRIO cla.

    O escopo vem de quem criou o evento, que e membro do cla do evento (a FK composta garante).
    E isso que mantem cada convite indo so para os membros do cla dele, mesmo com a conta sendo
    uma so para a plataforma inteira.
    """
    for evento in repo_plataforma.futuros_de_todos_os_clas(db, agora_local()):
        sincronizar(EscopoCla(db=db, membro=evento.criado_por), evento)


def conectar(db: Session, usuario: Usuario, email: str, refresh_token: str) -> IntegracaoGoogle:
    """Guarda a conta da plataforma e ja convida cada cla para o que estava marcado nele.

    Se ja havia uma conta, ela e trocada, e o acesso antigo e revogado no Google: uma conta que a
    plataforma nao usa mais nao deve continuar com permissao de mexer na agenda de ninguem.
    Quem chama confere antes que `usuario` e dono da plataforma.
    """
    for antiga in db.query(IntegracaoGoogle).all():
        try:
            google_agenda.revogar(google_agenda.decifrar(antiga.token_cifrado))
        except google_agenda.ErroGoogle:
            pass
        db.delete(antiga)
    db.flush()
    integracao = IntegracaoGoogle(
        email=email,
        token_cifrado=google_agenda.cifrar(refresh_token),
        conectado_por_usuario_id=usuario.id,
    )
    db.add(integracao)
    db.flush()
    log.info("conta google da plataforma conectada pelo usuario %s", usuario.id)
    sincronizar_todos(db)
    return integracao


def desconectar(db: Session) -> None:
    for integracao in db.query(IntegracaoGoogle).all():
        try:
            google_agenda.revogar(google_agenda.decifrar(integracao.token_cifrado))
        except google_agenda.ErroGoogle:
            pass
        db.delete(integracao)
    db.flush()


# ---------------------------------------------------------------------------------------------
# Para o calendario do painel e para "adicionar a minha agenda"
# ---------------------------------------------------------------------------------------------


def eventos_por_dia(escopo: EscopoCla, ano: int, mes: int) -> dict[date, list[Evento]]:
    de = datetime(ano, mes, 1)
    ate = datetime(ano + (mes == 12), mes % 12 + 1, 1)
    # A grade do calendario mostra dias do mes vizinho nas pontas. Uma semana de folga para cada
    # lado cobre essas pontas sem ler o ano inteiro.
    por_dia: dict[date, list[Evento]] = {}
    for evento in repo_eventos.do_periodo(escopo, de - timedelta(days=7), ate + timedelta(days=7)):
        por_dia.setdefault(evento.inicio.date(), []).append(evento)
    return por_dia


def link_google_agenda(evento: Evento) -> str:
    """ "Adicionar a minha agenda" para quem nao recebeu convite (cla sem conta conectada, ou quem
    usa outro email no Google). Nao passa pela conta do cla: abre o Google de quem clicou."""
    from urllib.parse import urlencode

    formato = "%Y%m%dT%H%M%S"
    parametros = {
        "action": "TEMPLATE",
        "text": evento.titulo,
        "dates": f"{evento.inicio.strftime(formato)}/{fim(evento).strftime(formato)}",
        "ctz": FUSO,
        "details": evento.descricao,
        "location": evento.local,
    }
    return f"https://calendar.google.com/calendar/render?{urlencode(parametros)}"
