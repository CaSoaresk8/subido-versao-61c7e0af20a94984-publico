"""A sessao sobrevive ao relogio andar para tras, e so a isso.

Um passo de relogio para tras (NTP corrigindo, VM migrando, maquina que dormiu) fazia o cookie
valido ser recusado, e o Starlette trata recusa como sessao vazia: deslogava todo mundo de uma vez.
Aqui se prova as duas metades da regra, porque afrouxar uma sem segurar a outra viraria buraco: o
carimbo no futuro passa, o carimbo velho continua expirando, e assinatura de fora continua caindo.

Estes testes nao tocam no banco e nao dependem da hora em que rodam: as duas pontas do relogio sao
fabricadas na mao, em vez de esperar a maquina se comportar mal.
"""

from __future__ import annotations

import pytest
from itsdangerous import TimestampSigner
from itsdangerous.exc import BadSignature, SignatureExpired

from app.config import SECRET_KEY
from app.sessao import AssinadorTolerante, SessaoEmCookie

MES = 60 * 60 * 24 * 30


class Adiantado(AssinadorTolerante):
    """Assina como se o relogio estivesse um minuto a frente do de quem vai conferir."""

    def get_timestamp(self) -> int:
        return super().get_timestamp() + 60


class Atrasado(AssinadorTolerante):
    """Assina como se fosse dois meses atras. E o dado velho de verdade."""

    def get_timestamp(self) -> int:
        return super().get_timestamp() - 2 * MES


def test_o_itsdangerous_sozinho_recusa_carimbo_no_futuro():
    """A premissa do conserto, conferida em vez de suposta.

    Sem esta assercao, os testes abaixo passariam iguais se o `itsdangerous` nunca tivesse recusado
    carimbo adiantado: provariam que o codigo roda, nao que ele resolve alguma coisa.
    """
    adiantado = Adiantado(str(SECRET_KEY)).sign(b"oi")
    with pytest.raises(SignatureExpired, match="< 0 seconds"):
        TimestampSigner(str(SECRET_KEY)).unsign(adiantado, max_age=MES)


def test_carimbo_no_futuro_e_aceito():
    """Carimbo a frente do relogio so pode ter saido daqui, porque o HMAC cobre o carimbo.

    Ninguem de fora consegue escolher um carimbo sem a chave, entao idade negativa nunca e ataque:
    e o proprio servidor tendo assinado antes do relogio ser corrigido para tras.
    """
    adiantado = Adiantado(str(SECRET_KEY)).sign(b"oi")
    assert AssinadorTolerante(str(SECRET_KEY)).unsign(adiantado, max_age=MES) == b"oi"


def test_carimbo_velho_continua_expirando():
    """O outro lado: afrouxar a idade negativa nao pode afrouxar o `max_age`.

    Dado velho e o risco de verdade, porque e no que um cookie roubado se transforma com o tempo.
    Se esta assercao ficar verde por engano, o conserto acima virou buraco.
    """
    velho = Atrasado(str(SECRET_KEY)).sign(b"oi")
    with pytest.raises(SignatureExpired):
        AssinadorTolerante(str(SECRET_KEY)).unsign(velho, max_age=MES)


def test_assinatura_de_outra_chave_continua_sendo_recusada():
    """A terceira metade: tolerar relogio nao pode virar tolerar assinatura que nao e nossa."""
    de_fora = TimestampSigner("chave-que-nao-e-a-daqui").sign(b"oi")
    with pytest.raises(BadSignature):
        AssinadorTolerante(str(SECRET_KEY)).unsign(de_fora, max_age=MES)


def test_o_app_monta_a_sessao_com_o_assinador_tolerante(app_web):
    """A ligacao, que e o que pode nao ter sido feita.

    Os testes acima ficariam verdes iguais se `app/main.py` tivesse continuado montando o
    `SessionMiddleware` do Starlette puro: eles provam a classe, nao o app. O que se confere aqui e
    que o middleware que de fato roda em cada pedido e o nosso, e que o assinador dele e o tolerante.
    """
    montados = [m for m in app_web.user_middleware if issubclass(m.cls, SessaoEmCookie)]
    assert len(montados) == 1, "a sessao em cookie nao esta montada uma vez so"

    middleware = montados[0].cls(lambda *_: None, **montados[0].kwargs)
    assert isinstance(middleware.signer, AssinadorTolerante)
    assert middleware.max_age == MES
