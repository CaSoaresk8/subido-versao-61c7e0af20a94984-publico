"""O convite: gerar, dizer se ainda vale, gastar um uso e revogar.

Este arquivo e o unico lugar que decide se um token vale. A decisao tem quatro partes (existe,
nao foi revogado, nao venceu, nao esgotou os usos) e elas precisam ser conferidas juntas sempre:
espalhar isso pelo router significaria que a tela de entrar confere as quatro e algum POST futuro
confere tres.

Quem gera e qualquer membro, sem excecao, porque o cla foi pedido sem lider. O que limita o dano
de um link encaminhado para quem nao devia nao e permissao de quem gerou: e a validade, o limite
de usos e a revogacao, que estao todas aqui.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.escopo import EscopoCla
from app.models import Convite, agora
from app.repositorios import contas as repo_contas
from app.servicos.auditoria import registrar

# 32 bytes de aleatorio, que o token_urlsafe escreve em 43 caracteres. O link e a credencial
# inteira: nao existe segundo fator nenhum atras dele, entao adivinhar tem que ser impossivel.
BYTES_DO_TOKEN = 32

VALIDADES = (1, 7, 30)
VALIDADE_PADRAO = 7
# Sem limite e o padrao porque o caso comum e chamar o cla inteiro com um link so. Quem quer um
# link para uma pessoa especifica poe 1 e o convite morre no primeiro uso.
MAXIMO_DE_USOS = 60


def gerar(escopo: EscopoCla, dias: int = VALIDADE_PADRAO, max_usos: int | None = None) -> Convite:
    """Cria o convite do cla ativo. Nao da commit: quem chamou decide se a operacao inteira vale."""
    convite = Convite(
        cla_id=escopo.cla_id,
        token=secrets.token_urlsafe(BYTES_DO_TOKEN),
        criado_por_id=escopo.membro_id,
        expira_em=agora() + timedelta(days=dias),
        max_usos=max_usos,
        usos=0,
    )
    escopo.db.add(convite)
    escopo.db.flush()
    registrar(
        escopo,
        "criou",
        "convite",
        convite.id,
        f"Gerou convite válido por {dias} dia(s)"
        + (f", limite de {max_usos} uso(s)" if max_usos else ", sem limite de usos"),
    )
    return convite


def validar_pedido(dias: int, max_usos: int | None) -> str | None:
    """A mensagem do primeiro problema do formulario, ou None.

    O formulario manda numero, e numero vindo de fora nao e numero: e texto que parece numero.
    Sem este teto, `dias=999999` geraria um convite que na pratica nunca vence, que e o oposto do
    que validade quer dizer.
    """
    if dias not in VALIDADES:
        return "Escolha uma validade da lista."
    if max_usos is not None and not 1 <= max_usos <= MAXIMO_DE_USOS:
        return f"O limite de usos vai de 1 a {MAXIMO_DE_USOS}, ou pode ficar vazio."
    return None


# As quatro razoes para um convite nao servir, escritas para dois leitores diferentes. Quem chegou
# com o link precisa saber o que fazer agora; quem esta dentro do cla olhando a lista precisa de um
# rotulo curto do estado. Sao duas frases, mas uma decisao so: as duas leem o mesmo _codigo().
RECUSAS = {
    "inexistente": "Esse link de convite não existe. Peça um novo para quem te chamou.",
    "revogado": "Esse convite foi revogado. Peça um novo para quem te chamou.",
    "vencido": "Esse convite venceu. Peça um novo para quem te chamou.",
    "esgotado": "Esse convite já atingiu o limite de usos. Peça um novo para quem te chamou.",
}
SITUACOES = {
    "inexistente": "não existe",
    "revogado": "revogado",
    "vencido": "vencido",
    "esgotado": "limite de usos atingido",
}


def _codigo(convite: Convite | None) -> str | None:
    """A decisao, num lugar so: por que este convite nao vale, ou None quando vale.

    A ordem importa pouco para quem le, mas importa para quem escreve: um convite pode estar
    revogado E vencido, e a primeira razao encontrada e a que sai. Nenhuma das duas telas precisa
    da lista completa.
    """
    if convite is None:
        return "inexistente"
    if convite.revogado_em is not None:
        return "revogado"
    if convite.expira_em <= agora():
        return "vencido"
    if convite.max_usos is not None and convite.usos >= convite.max_usos:
        return "esgotado"
    return None


def motivo_de_recusa(convite: Convite | None) -> str | None:
    """A frase para quem chegou com o link, ou None quando o convite vale.

    Token que nao existe e token que venceu dao mensagens diferentes de proposito: aqui nao ha o
    que esconder, porque quem chegou com um link quebrado precisa saber se pede outro ou se
    procurou errado. Nao e o caso do 404 de id alheio, onde a informacao a mais e o que se quer
    negar; um convite invalido nao conta nada sobre o cla.
    """
    codigo = _codigo(convite)
    return RECUSAS[codigo] if codigo else None


def situacao(convite: Convite) -> str:
    """O rotulo curto para a lista de convites do cla."""
    codigo = _codigo(convite)
    return SITUACOES[codigo] if codigo else "vale"


def vale(convite: Convite) -> bool:
    """Para a tela mostrar o link do que ainda serve e riscar o resto."""
    return _codigo(convite) is None


def abrir(db: Session, token: str) -> tuple[Convite | None, str | None]:
    """Procura o token e ja diz se ele vale. Devolve (convite, motivo_da_recusa).

    Os dois passos andam juntos em todo lugar que le convite, entao andam juntos aqui tambem: quem
    chama nao tem como pegar o convite e esquecer de conferir.
    """
    convite = repo_contas.convite_por_token(db, token)
    return convite, motivo_de_recusa(convite)


def consumir(escopo: EscopoCla, convite: Convite) -> None:
    """Gasta um uso do convite e anota quem entrou por ele.

    Recebe o escopo de quem ACABOU de entrar, e nao o de quem gerou: e por isso que o log fica no
    cla certo com o membro certo. Sem isso, "entrou por convite" seria uma linha sem autor.
    """
    convite.usos += 1
    registrar(
        escopo,
        "usou",
        "convite",
        convite.id,
        f"Entrou no clã pelo convite ({convite.usos}º uso)",
    )


def revogar(escopo: EscopoCla, convite: Convite) -> None:
    """Mata o link sem apagar a linha: o historico de quem convidou quem tem que continuar lendo.

    Revogar duas vezes nao muda a data da primeira. A tela esconde o botao de quem ja foi
    revogado, mas dois cliques no mesmo botao em duas abas chegam aqui duas vezes.
    """
    if convite.revogado_em is not None:
        return
    convite.revogado_em = agora()
    registrar(escopo, "revogou", "convite", convite.id, "Revogou o convite")
