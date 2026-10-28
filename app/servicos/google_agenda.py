"""A conversa com o Google: o login OAuth de UMA conta por cla e os eventos com convidados.

Por que uma conta so, e nao cada membro conectando a sua: o convite que o Google Agenda manda e o
formato que o Gmail mais reconhece (aparece com Sim/Nao/Talvez e entra na agenda de quem recebe), e
para mandar ele basta que QUEM ENVIA tenha dado permissao. Quem recebe nao conecta nada, so recebe
um email no endereco com que se cadastrou no app.

Nada aqui sabe de cla, membro ou banco: recebe o refresh token e um corpo de evento, devolve o id
do Google ou levanta `ErroGoogle`. Quem decide o que enviar, para quem e o que fazer com a falha e
`servicos/agenda.py`.

Sem SDK do Google de proposito: sao quatro chamadas HTTP (token, userinfo, eventos, revogar), e o
`google-api-python-client` traria dezenas de MB de dependencia para elas. `transporte` e o unico
ponto que fala com a rede, e e ele que os testes trocam por um Google de mentira.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import GOOGLE_CLIENT_ID, SECRET_KEY, segredo_google

URL_AUTORIZACAO = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_USUARIO = "https://openidconnect.googleapis.com/v1/userinfo"
URL_REVOGAR = "https://oauth2.googleapis.com/revoke"
URL_EVENTOS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

# `calendar.events` e o menor escopo que cria evento com convidado. `calendar` inteiro daria ao app
# leitura de TODAS as agendas da conta, e nada aqui precisa disso. `email` e para a tela mostrar qual
# conta esta mandando os convites.
ESCOPOS = "openid email https://www.googleapis.com/auth/calendar.events"

TEMPO_LIMITE = 10


class ErroGoogle(Exception):
    """Falha falando com o Google, ja com a frase que a tela pode mostrar.

    `desconectou` separa o caso que so a pessoa resolve (a conta tirou a permissao, ou a senha
    mudou) do que resolve tentando de novo (rede, instabilidade do Google).
    """

    def __init__(self, mensagem: str, status: int = 0, desconectou: bool = False) -> None:
        super().__init__(mensagem)
        self.status = status
        self.desconectou = desconectou


@dataclass(frozen=True)
class Resposta:
    status: int
    corpo: dict


def _http(
    metodo: str,
    url: str,
    form: dict | None = None,
    corpo: dict | None = None,
    token: str | None = None,
) -> Resposta:
    cabecalhos = {"Accept": "application/json"}
    dados = None
    if form is not None:
        dados = urllib.parse.urlencode(form).encode()
        cabecalhos["Content-Type"] = "application/x-www-form-urlencoded"
    elif corpo is not None:
        dados = json.dumps(corpo).encode()
        cabecalhos["Content-Type"] = "application/json"
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    pedido = urllib.request.Request(url, data=dados, headers=cabecalhos, method=metodo)
    try:
        with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE) as resposta:
            bruto = resposta.read()
            return Resposta(resposta.status, json.loads(bruto) if bruto else {})
    except urllib.error.HTTPError as erro:
        bruto = erro.read()
        try:
            return Resposta(erro.code, json.loads(bruto) if bruto else {})
        except ValueError:
            return Resposta(erro.code, {})
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        raise ErroGoogle(
            "Não consegui falar com o Google agora. Tente de novo em instantes."
        ) from erro


# O unico ponto de rede. Os testes trocam por um Google de mentira (tests/google_falso.py).
transporte = _http


# ---------------------------------------------------------------------------------------------
# O refresh token guardado no banco
# ---------------------------------------------------------------------------------------------


def _fernet() -> Fernet:
    """Chave derivada da SECRET_KEY, e nao a propria: a SECRET_KEY assina cookie, e usar o mesmo
    segredo cru para duas funcoes diferentes e o tipo de atalho que vira brecha quando uma delas
    muda. Trocar a SECRET_KEY invalida os tokens guardados, e o efeito e a tela pedir para conectar
    o Google de novo, que e o comportamento certo depois de uma troca de chave."""
    chave = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"subido-cla", info=b"google-refresh-token"
    ).derive(SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(chave))


def cifrar(refresh_token: str) -> str:
    return _fernet().encrypt(refresh_token.encode()).decode()


def decifrar(token_cifrado: str) -> str:
    try:
        return _fernet().decrypt(token_cifrado.encode()).decode()
    except InvalidToken as erro:
        raise ErroGoogle(
            "A conexão com o Google precisa ser refeita. Conecte a conta de novo na Agenda.",
            desconectou=True,
        ) from erro


# ---------------------------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------------------------


def url_de_autorizacao(redirect_uri: str, state: str) -> str:
    """`access_type=offline` + `prompt=consent` e o par que garante o refresh token.

    Sem `prompt=consent`, a segunda vez que a mesma conta autoriza o Google devolve so o access token
    (que morre em uma hora), e o cla ficaria mandando convite por uma hora e depois nunca mais.
    """
    parametros = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ESCOPOS,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{URL_AUTORIZACAO}?{urllib.parse.urlencode(parametros)}"


def trocar_codigo(codigo: str, redirect_uri: str) -> tuple[str, str]:
    """O codigo que o Google devolveu vira (email da conta, refresh token)."""
    resposta = transporte(
        "POST",
        URL_TOKEN,
        form={
            "code": codigo,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": segredo_google(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    if resposta.status != 200:
        raise ErroGoogle("O Google recusou a conexão. Tente conectar de novo.", resposta.status)
    refresh = resposta.corpo.get("refresh_token")
    acesso = resposta.corpo.get("access_token")
    escopos = resposta.corpo.get("scope", "")
    if "calendar.events" not in escopos:
        # A tela de consentimento do Google deixa desmarcar a agenda e aceitar so o email. Aceitar a
        # conexao assim daria um cla "conectado" que nao consegue mandar convite nenhum.
        raise ErroGoogle(
            "A permissão de agenda não foi marcada. Conecte de novo e deixe a caixa da agenda marcada."
        )
    if not refresh or not acesso:
        raise ErroGoogle("O Google não devolveu o acesso permanente. Tente conectar de novo.")
    usuario = transporte("GET", URL_USUARIO, token=acesso)
    email = usuario.corpo.get("email", "") if usuario.status == 200 else ""
    if not email:
        raise ErroGoogle("Não consegui ler qual conta Google foi conectada. Tente de novo.")
    _guardar_acesso(refresh, acesso, int(resposta.corpo.get("expires_in", 3600)))
    return email.lower(), refresh


def revogar(refresh_token: str) -> None:
    """Melhor esforco: desconectar no app vale mesmo que o Google esteja fora do ar."""
    try:
        transporte("POST", URL_REVOGAR, form={"token": refresh_token})
    except ErroGoogle:
        pass
    _esquecer_acesso(refresh_token)


# O access token vive uma hora. Guardar em memoria evita uma ida ao Google a cada evento salvo; a
# chave e o proprio refresh token, entao dois clas nunca dividem acesso. Perder isto num reinicio da
# maquina so custa uma renovacao.
_acessos: dict[str, tuple[str, float]] = {}
_trava = threading.Lock()


def _guardar_acesso(refresh: str, acesso: str, dura_segundos: int) -> None:
    with _trava:
        _acessos[refresh] = (acesso, time.monotonic() + dura_segundos - 120)


def _esquecer_acesso(refresh: str) -> None:
    with _trava:
        _acessos.pop(refresh, None)


def _acesso(refresh: str) -> str:
    with _trava:
        guardado = _acessos.get(refresh)
    if guardado and guardado[1] > time.monotonic():
        return guardado[0]
    resposta = transporte(
        "POST",
        URL_TOKEN,
        form={
            "refresh_token": refresh,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": segredo_google(),
            "grant_type": "refresh_token",
        },
    )
    if resposta.status == 400 and resposta.corpo.get("error") == "invalid_grant":
        raise ErroGoogle(
            "A conta Google tirou a permissão do app. Conecte a conta de novo na Agenda.",
            400,
            desconectou=True,
        )
    if resposta.status != 200 or "access_token" not in resposta.corpo:
        raise ErroGoogle("O Google não renovou o acesso agora. Tente de novo.", resposta.status)
    _guardar_acesso(
        refresh, resposta.corpo["access_token"], int(resposta.corpo.get("expires_in", 3600))
    )
    return resposta.corpo["access_token"]


# ---------------------------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------------------------


def _url_evento(evento_id: str = "") -> str:
    # sendUpdates=all e o que faz o Google mandar o email para cada convidado; sem ele o evento
    # aparece na agenda de quem conectou e mais ninguem fica sabendo.
    base = f"{URL_EVENTOS}/{urllib.parse.quote(evento_id)}" if evento_id else URL_EVENTOS
    return f"{base}?sendUpdates=all"


def _falha(resposta: Resposta, acao: str) -> ErroGoogle:
    if resposta.status in (401, 403):
        return ErroGoogle(
            f"O Google não deixou {acao}: a conta perdeu a permissão de agenda. Conecte de novo.",
            resposta.status,
            desconectou=True,
        )
    return ErroGoogle(
        f"O Google não deixou {acao} agora (erro {resposta.status}).", resposta.status
    )


def criar_evento(refresh: str, corpo: dict) -> str:
    resposta = transporte("POST", _url_evento(), corpo=corpo, token=_acesso(refresh))
    if resposta.status not in (200, 201) or not resposta.corpo.get("id"):
        raise _falha(resposta, "criar o convite")
    return resposta.corpo["id"]


def atualizar_evento(refresh: str, evento_id: str, corpo: dict) -> str:
    """Atualiza o convite que ja existe. Se ele sumiu do Google, cria outro e devolve o id novo.

    Sumir acontece de verdade: quem conectou pode apagar o evento direto na agenda dele, ou o cla
    pode ter trocado de conta. Nos dois casos o que o cla quer e que o convite exista.
    """
    acesso = _acesso(refresh)
    atual = transporte("GET", f"{URL_EVENTOS}/{urllib.parse.quote(evento_id)}", token=acesso)
    if atual.status in (404, 410) or atual.corpo.get("status") == "cancelled":
        # Cancelado conta como sumido: PUT num evento cancelado devolve 200 e ele CONTINUA
        # cancelado para os convidados.
        return criar_evento(refresh, corpo)
    if atual.status != 200:
        raise _falha(atual, "atualizar o convite")
    # A lista de convidados vai inteira no PUT. Copiar a resposta de quem ja respondeu e o que
    # impede uma edicao de titulo de apagar o "Sim" de quem confirmou presenca.
    respostas = {
        (c.get("email") or "").lower(): c.get("responseStatus")
        for c in atual.corpo.get("attendees", [])
        if c.get("responseStatus")
    }
    corpo = {
        **corpo,
        "attendees": [
            {**c, "responseStatus": respostas[c["email"]]} if c["email"] in respostas else c
            for c in corpo.get("attendees", [])
        ],
    }
    resposta = transporte("PUT", _url_evento(evento_id), corpo=corpo, token=acesso)
    if resposta.status in (404, 410):
        return criar_evento(refresh, corpo)
    if resposta.status != 200:
        raise _falha(resposta, "atualizar o convite")
    return evento_id


def cancelar_evento(refresh: str, evento_id: str) -> None:
    """Cancela para todo mundo. Ja apagado conta como sucesso: o estado pedido e o que ficou."""
    resposta = transporte("DELETE", _url_evento(evento_id), token=_acesso(refresh))
    if resposta.status not in (200, 204, 404, 410):
        raise _falha(resposta, "cancelar o convite")
