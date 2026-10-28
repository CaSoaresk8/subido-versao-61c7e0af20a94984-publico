"""A sessao em cookie, tolerante a relogio que anda para tras.

O Starlette assina o cookie com `TimestampSigner` e confere com `max_age`. O `itsdangerous` recusa
nao so o carimbo velho demais como tambem o carimbo no FUTURO (`age < 0`), e o Starlette trata essa
recusa como assinatura invalida: esvazia a sessao. Na pratica, a pessoa e deslogada no meio do uso.

Carimbo no futuro nao e ataque. O HMAC cobre o carimbo, entao ninguem de fora consegue escolher um:
um cookie datado a frente so pode ter saido DAQUI, com o relogio adiantado, e ter voltado depois que
o relogio foi corrigido. Recusa-lo nao protege de nada e desloga todo mundo que entrou na janela
entre o carimbo e a correcao. Passo de relogio para tras acontece em NTP, em migracao de VM e em
maquina que dormiu, e nesse instante ninguem quer descobrir que a base inteira caiu no login.

O que NAO se afrouxa: `max_age` continua valendo para cookie velho, que e o risco de verdade (cookie
roubado precisa deixar de valer). Aqui so se deixa de exigir que o relogio nunca ande para tras.

Achado assim: a suite ficava vermelha em cerca de um terco das rodadas, em testes diferentes a cada
vez. O relogio do WSL desta maquina oscila 19,6s para tras a cada 4,6s, e a suite roda em 1,6s, o
que dava justamente essa proporcao. O sintoma era sempre 401 com o cookie certo na mao.
"""

from __future__ import annotations

from datetime import datetime, timezone

import itsdangerous
from itsdangerous.exc import SignatureExpired
from starlette.middleware.sessions import SessionMiddleware


class AssinadorTolerante(itsdangerous.TimestampSigner):
    """`TimestampSigner` que aceita carimbo no futuro, e so ele."""

    def unsign(self, signed_value, max_age=None, return_timestamp=False):  # type: ignore[override]
        try:
            return super().unsign(signed_value, max_age, return_timestamp)
        except SignatureExpired as erro:
            assinado = erro.date_signed
            if assinado is None or assinado <= datetime.now(timezone.utc):
                # Carimbo velho de verdade: e para expirar mesmo.
                raise
            # Carimbo a frente do relogio. A assinatura ja foi conferida e passou la em cima; o que
            # sobrou para decidir era a idade, e idade negativa nao diz nada sobre validade.
            return super().unsign(signed_value, None, return_timestamp)


class SessaoEmCookie(SessionMiddleware):
    """O middleware do Starlette com o assinador acima no lugar do padrao."""

    def __init__(self, app, secret_key, **resto) -> None:
        super().__init__(app, secret_key, **resto)
        self.signer = AssinadorTolerante(str(secret_key))
