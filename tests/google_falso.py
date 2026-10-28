"""Um Google de mentira para os testes da agenda: responde no formato da API real, sem rede.

Entra no lugar de `app.servicos.google_agenda.transporte`. Guarda os eventos em memoria, com o
`responseStatus` de cada convidado, e deixa o teste provocar as falhas que acontecem de verdade:
Google fora do ar (`falhar_com=500`), permissao retirada (`sem_permissao`), evento apagado direto
na agenda de quem conectou (`apagar_por_fora`).

Ele NAO substitui o teste com o Google de verdade. O que ele prova e o lado do app: que o app manda
o que deveria mandar, na ordem certa, e se comporta direito com cada resposta. Se o Google mudar o
formato de alguma resposta, isto aqui continua verde, e e por isso que a validacao final e feita
conectando uma conta real.
"""

from __future__ import annotations

import itertools
import urllib.parse

from app.servicos import google_agenda
from app.servicos.google_agenda import Resposta


class GoogleFalso:
    def __init__(self, email: str = "agenda@cla-teste.com") -> None:
        self.email = email
        self.eventos: dict[str, dict] = {}
        self.chamadas: list[tuple[str, str]] = []
        self.falhar_com: int | None = None
        self.sem_permissao = False
        self.escopo_concedido = google_agenda.ESCOPOS
        self.revogados: list[str] = []
        self._ids = itertools.count(1)
        self._refresh = itertools.count(1)

    # -- o que o teste usa ---------------------------------------------------------------------

    def ativos(self) -> list[dict]:
        return [e for e in self.eventos.values() if e.get("status") != "cancelled"]

    def responder(self, evento_id: str, email: str, resposta: str) -> None:
        """Simula o convidado clicando em Sim/Nao no email."""
        for convidado in self.eventos[evento_id]["attendees"]:
            if convidado["email"] == email:
                convidado["responseStatus"] = resposta

    def apagar_por_fora(self, evento_id: str) -> None:
        self.eventos.pop(evento_id)

    # -- o transporte -------------------------------------------------------------------------

    def __call__(self, metodo, url, form=None, corpo=None, token=None) -> Resposta:
        caminho = urllib.parse.urlsplit(url)
        self.chamadas.append((metodo, url))
        if self.falhar_com:
            return Resposta(self.falhar_com, {"error": {"message": "backend error"}})

        if url == google_agenda.URL_TOKEN:
            if form.get("grant_type") == "refresh_token" and self.sem_permissao:
                return Resposta(400, {"error": "invalid_grant"})
            resposta = {
                "access_token": f"acesso-{next(self._refresh)}",
                "expires_in": 3600,
                "scope": self.escopo_concedido,
            }
            if form.get("grant_type") == "authorization_code":
                resposta["refresh_token"] = f"refresh-{form['code']}"
            return Resposta(200, resposta)
        if url == google_agenda.URL_USUARIO:
            return Resposta(200, {"email": self.email})
        if url == google_agenda.URL_REVOGAR:
            self.revogados.append(form["token"])
            return Resposta(200, {})

        assert token, "chamada de agenda sem access token"
        base = google_agenda.URL_EVENTOS
        if metodo in ("POST", "PUT", "DELETE"):
            assert "sendUpdates=all" in (caminho.query or ""), "o Google nao mandaria email"
        evento_id = (
            urllib.parse.unquote(caminho.path.split("/events/")[1]) if "/events/" in url else ""
        )
        if metodo == "POST" and url.startswith(base):
            novo = {**corpo, "id": f"g{next(self._ids)}", "status": "confirmed"}
            novo["attendees"] = [{**c, "responseStatus": "needsAction"} for c in corpo["attendees"]]
            self.eventos[novo["id"]] = novo
            return Resposta(200, novo)
        if evento_id not in self.eventos:
            return Resposta(404, {"error": {"message": "Not Found"}})
        atual = self.eventos[evento_id]
        if metodo == "GET":
            return Resposta(200, atual)
        if metodo == "PUT":
            # O PUT real substitui o evento inteiro, inclusive a lista de convidados: o que nao for
            # mandado some. E exatamente o comportamento que o app precisa sobreviver.
            novo = {**corpo, "id": evento_id, "status": atual.get("status", "confirmed")}
            novo["attendees"] = [
                {"responseStatus": "needsAction", **c} for c in corpo.get("attendees", [])
            ]
            self.eventos[evento_id] = novo
            return Resposta(200, novo)
        if metodo == "DELETE":
            atual["status"] = "cancelled"
            return Resposta(204, {})
        raise AssertionError(f"chamada inesperada: {metodo} {url}")
