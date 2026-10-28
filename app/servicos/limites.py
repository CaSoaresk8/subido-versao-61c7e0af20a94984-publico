"""Limites de uso por IP: senha em massa, cadastro em massa e o video de 22 MB em laco.

O app nao tinha nenhum. Com o endereco circulando em comunidade aberta, tres coisas ficam baratas
demais para quem quiser atrapalhar:

1. **Testar senha.** Sem limite, um script tenta milhares de senhas na conta de quem quiser.
2. **Criar conta e cla sem parar.** Enche a base de lixo e polui a lista de todo mundo.
3. **Baixar o tutorial em laco.** Sao 22 MB por download, numa maquina so, com banda paga. E o
   jeito mais barato de deixar o app lento para quem esta usando e de gerar conta no fim do mes.

A contagem e em MEMORIA, de proposito. A maquina e uma so, entao um dicionario resolve; Redis seria
uma peca a mais para manter, com estado que hoje nao precisa sobreviver a nada. O que se perde e
que o deploy zera os contadores, e esse preco e aceitavel: deploy acontece algumas vezes por dia, e
quem estava sendo barrado ganha alguns minutos a mais. O que NAO se perde e o objetivo: transformar
"milhares de tentativas por minuto" em "algumas por minuto", que ja tira o ataque da mesa.

O relogio entra por parametro (`agora`) para o teste poder andar no tempo sem dormir de verdade.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass

# (quantas tentativas, em quantos segundos, quanto tempo fica bloqueado)
SENHA = (8, 15 * 60, 15 * 60)
# Cadastro e criacao de cla. Dez por hora por IP deixa passar um escritorio inteiro entrando junto
# (todo mundo sai com o mesmo IP) e ainda assim recusa robo.
CADASTRO = (10, 60 * 60, 60 * 60)
# O video. Dez por hora por IP sao 220 MB, muito acima de qualquer uso humano: quem assiste, assiste
# uma vez, e o navegador guarda.
VIDEO = (10, 60 * 60, 30 * 60)


@dataclass
class Registro:
    marcas: list[float]
    bloqueado_ate: float = 0.0


class Limitador:
    """Contador de eventos por chave, com janela deslizante e castigo.

    Uma instancia por tipo de limite (senha, cadastro, video), para um nao contaminar o outro.
    """

    def __init__(self, regra: tuple[int, int, int], nome: str = "") -> None:
        self.maximo, self.janela, self.castigo = regra
        self.nome = nome
        self._registros: dict[str, Registro] = defaultdict(lambda: Registro(marcas=[]))
        self._trava = threading.Lock()

    def bloqueado(self, chave: str, agora: float | None = None) -> int:
        """Quantos segundos faltam para liberar. Zero quer dizer liberado."""
        agora = time.monotonic() if agora is None else agora
        with self._trava:
            registro = self._registros.get(chave)
            if registro is None:
                return 0
            return max(0, int(registro.bloqueado_ate - agora))

    def registrar(self, chave: str, agora: float | None = None) -> int:
        """Conta mais uma tentativa. Devolve os segundos de bloqueio, ou zero se ainda pode."""
        agora = time.monotonic() if agora is None else agora
        with self._trava:
            registro = self._registros[chave]
            if registro.bloqueado_ate > agora:
                return int(registro.bloqueado_ate - agora)
            # Janela deslizante: o que saiu da janela deixa de contar, senao alguem que errou uma
            # senha de manha ficaria mais perto do bloqueio a noite, sem ter feito nada.
            registro.marcas = [m for m in registro.marcas if agora - m < self.janela]
            registro.marcas.append(agora)
            if len(registro.marcas) >= self.maximo:
                registro.bloqueado_ate = agora + self.castigo
                registro.marcas.clear()
                return self.castigo
            return 0

    def limpar(self, chave: str) -> None:
        """Esquece a chave. O login chama isto quando a senha ACERTA: quem entrou nao e atacante,
        e quem errou tres vezes antes de lembrar a senha nao merece carregar isso por 15 minutos."""
        with self._trava:
            self._registros.pop(chave, None)

    def esquecer_tudo(self) -> None:
        with self._trava:
            self._registros.clear()


senha = Limitador(SENHA, "senha")
cadastro = Limitador(CADASTRO, "cadastro")
video = Limitador(VIDEO, "video")


def de_onde(request) -> str:
    """O IP de quem pediu.

    `request.client.host` ja e o IP real: o uvicorn roda com --proxy-headers e o proxy do Fly manda
    o X-Forwarded-For. Sem aquele parametro, isto aqui seria o IP do proxy e o limite valeria para
    o mundo inteiro de uma vez, que e pior do que nao ter limite.
    """
    return request.client.host if request.client else "desconhecido"


def em_minutos(segundos: int) -> str:
    """Para a frase que a pessoa le. Segundo exato nao ajuda ninguem e ainda conta ao atacante
    exatamente quando tentar de novo."""
    minutos = max(1, round(segundos / 60))
    return "1 minuto" if minutos == 1 else f"{minutos} minutos"
