"""O formato de cada coisa em JSON, num lugar so.

Isto e o contrato: e daqui que sai o que o React vai ler na fase 5, e e por isso que nao ha um
`jsonable_encoder(missao)` solto em rota nenhuma. Serializar o objeto inteiro por reflexao parece
economia e nao e: entregaria `senha_hash` no dia em que alguem puser um relacionamento novo no
modelo, e mudaria o contrato sem ninguem ter escrito a mudanca.

Duas regras que valem para todas as funcoes daqui:

1. **Data sai em ISO, sempre, e `None` continua `None`.** `2026-09-30` e `2026-09-30T14:02:11`
   atravessam qualquer linguagem sem combinar formato, e o `null` e o que distingue "sem prazo" de
   "prazo hoje". Formatar para leitura humana e trabalho da tela, que e quem sabe o idioma e o fuso
   de quem esta olhando.
2. **Nada de credencial e nada de email de terceiro.** `membro()` devolve id e nome, que e o que o
   ranking mostra. O email so aparece em `usuario()`, e `usuario()` so e chamado para a conta de
   quem esta pedindo. Uma lista de membros com email dentro seria um jeito de qualquer pessoa do
   cla baixar o email de todo mundo, e nenhuma tela precisa disso.
"""

from __future__ import annotations

from datetime import date, datetime

from app.deps import simbolo_do_cla
from app.models import (
    Cla,
    Coluna,
    Convite,
    Entrega,
    Log,
    Membro,
    Missao,
    TarefaPessoal,
    Usuario,
)
from app.servicos import convites as servico_convites


def data(valor: date | None) -> str | None:
    return valor.isoformat() if valor is not None else None


def instante(valor: datetime | None) -> str | None:
    return valor.isoformat() if valor is not None else None


def usuario(registro: Usuario) -> dict:
    """So para a conta de quem pediu. Ver a regra 2 do topo do arquivo.

    O telefone entra pela mesma porta estreita do email, e nao em `membro()`: o dono do numero ve o
    proprio, e mais ninguem. `None` sai como `None` porque as contas anteriores ao campo nao tem
    telefone, e inventar string vazia diria que a pessoa informou algo.
    """
    return {
        "id": registro.id,
        "nome": registro.nome,
        "email": registro.email,
        "telefone": registro.telefone,
    }


def membro(registro: Membro) -> dict:
    return {"id": registro.id, "nome": registro.nome}


def membro_do_cla(registro: Membro) -> dict:
    """A versao da lista de membros, com a data de entrada. Email continua de fora.

    `membro()` e o que aparece encaixado dentro de outra coisa (uma linha do ranking, o autor de um
    log) e nao carrega data nenhuma: a lista de membros e a unica tela que mostra quem entrou
    quando, e carregar esse campo em toda entrega seria engordar o quadro inteiro por causa de uma
    tela so.
    """
    return {**membro(registro), "entrou_em": instante(registro.entrou_em)}


def cla(registro: Cla) -> dict:
    """`simbolo` ja vem como URL pronta, inclusive o icone do app para o cla sem logo.

    O banco guarda so o nome do arquivo, e montar "/logos/" + nome e decisao de rota. Se cada tela
    montasse esse endereco por conta, mudar o `app.mount` obrigaria a caçar as copias.
    """
    return {
        "id": registro.id,
        "nome": registro.nome,
        "simbolo": simbolo_do_cla(registro),
        "criado_em": instante(registro.criado_em),
    }


def convite(registro: Convite, link_base: str) -> dict:
    """`situacao` e `vale` saem do servico, e nao de uma conta refeita aqui.

    Sao as quatro condicoes de validade (existe, nao revogado, nao vencido, nao esgotado) decididas
    no unico lugar que decide isso. Recalcular aqui daria uma segunda versao da regra, e a lista de
    convites da tela diria "vale" para um token que a rota de entrar recusa.
    """
    return {
        "id": registro.id,
        "token": registro.token,
        "link": f"{link_base}/convite/{registro.token}",
        "criado_em": instante(registro.criado_em),
        "criado_por": membro(registro.criado_por) if registro.criado_por else None,
        "expira_em": instante(registro.expira_em),
        "max_usos": registro.max_usos,
        "usos": registro.usos,
        "revogado_em": instante(registro.revogado_em),
        "situacao": servico_convites.situacao(registro),
        "vale": servico_convites.vale(registro),
    }


def missao(registro: Missao) -> dict:
    return {
        "id": registro.id,
        "titulo": registro.titulo,
        "descricao": registro.descricao,
        "pontos": registro.pontos,
        "vencimento": data(registro.vencimento),
        "exige_resposta": registro.exige_resposta,
        "rotulo_resposta": registro.rotulo_resposta,
        "criada_em": instante(registro.criada_em),
        "criada_por_id": registro.criada_por_id,
        "excluida_em": instante(registro.excluida_em),
        "ativa": registro.ativa,
    }


def entrega(registro: Entrega | None, com_membro: bool = False) -> dict | None:
    """`None` entra e `None` sai: quem nunca mexeu numa missao nao tem entrega, e isso e um estado.

    Inventar uma entrega vazia com status "a_fazer" faria a tela nao conseguir distinguir "ainda
    nao olhei" de "olhei e deixei em a fazer", e o dashboard mostra as duas coisas diferentes.
    """
    if registro is None:
        return None
    saida = {
        "id": registro.id,
        "missao_id": registro.missao_id,
        "membro_id": registro.membro_id,
        "status": registro.status,
        "resposta": registro.resposta,
        "observacao": registro.observacao,
        "concluida_em": instante(registro.concluida_em),
        "atualizada_em": instante(registro.atualizada_em),
        "coluna_id": registro.coluna_id,
        "ordem": registro.ordem,
    }
    if com_membro:
        saida["membro"] = membro(registro.membro)
    return saida


def tarefa(registro: TarefaPessoal) -> dict:
    return {
        "id": registro.id,
        "titulo": registro.titulo,
        "descricao": registro.descricao,
        "status": registro.status,
        "prazo": data(registro.prazo),
        "criada_em": instante(registro.criada_em),
        "excluida_em": instante(registro.excluida_em),
        "coluna_id": registro.coluna_id,
        "ordem": registro.ordem,
    }


def coluna(registro: Coluna) -> dict:
    return {"id": registro.id, "nome": registro.nome, "ordem": registro.ordem}


def log(registro: Log) -> dict:
    return {
        "id": registro.id,
        "acao": registro.acao,
        "entidade": registro.entidade,
        "entidade_id": registro.entidade_id,
        "detalhe": registro.detalhe,
        "criado_em": instante(registro.criado_em),
        "membro": membro(registro.membro) if registro.membro else None,
    }


def item_do_quadro(item: dict) -> dict:
    """O cartao que `servicos/quadro.montar_itens` monta, com o prazo em ISO.

    O dict chega pronto do servico, com missao e tarefa pessoal ja no mesmo formato, e e esse o
    ponto: o quadro desenha os dois tipos com o mesmo desenho, entao eles atravessam a API com a
    mesma forma. So o `prazo` muda, porque la ele e `date` e aqui tem que ser texto.
    """
    return {**item, "prazo": data(item["prazo"])}


def grupo_do_quadro(grupo: dict) -> dict:
    return {**grupo, "itens": [item_do_quadro(i) for i in grupo["itens"]]}


def _linha_do_relatorio(linha: dict) -> dict:
    return {"missao": missao(linha["missao"]), "entrega": entrega(linha["entrega"])}


def relatorio(dados: dict) -> dict:
    return {
        "pontos": dados["pontos"],
        "total_missoes": dados["total_missoes"],
        "concluidas": [_linha_do_relatorio(linha) for linha in dados["concluidas"]],
        "fazendo": [_linha_do_relatorio(linha) for linha in dados["fazendo"]],
        "a_fazer": [_linha_do_relatorio(linha) for linha in dados["a_fazer"]],
    }


def linha_do_ranking(linha: dict) -> dict:
    """O relatorio vai junto, no mesmo pedido, e nao numa rota separada por pessoa.

    Ele e o que abre dentro da linha quando alguem clica, e ja foi calculado para dar os pontos da
    linha: devolver so o total obrigaria a tela a pedir de novo, por pessoa, a mesma conta que
    acabou de ser feita. Num cla de 17 pessoas isso e um pedido contra dezessete.
    """
    return {
        "membro": membro(linha["membro"]),
        "posicao": linha["posicao"],
        "pontos": linha["pontos"],
        "concluidas": linha["concluidas"],
        "pendentes": linha["pendentes"],
        "ultima_atividade": instante(linha["ultima_atividade"]),
        "relatorio": relatorio(linha["relatorio"]),
    }


def barra_do_grafico(barra: dict) -> dict:
    return {
        "missao": missao(barra["missao"]),
        "quantidade": barra["quantidade"],
        "percentual": barra["percentual"],
        "quem": barra["quem"],
    }


def numeros(dados: dict) -> dict:
    return {
        **dados,
        "vencendo": [missao(m) for m in dados["vencendo"]],
        "vencidas": [missao(m) for m in dados["vencidas"]],
    }


def dia_do_calendario(dia: dict) -> dict:
    return {**dia, "data": data(dia["data"])}


def evento(registro) -> dict:
    """O evento da agenda. `inicio` sai como hora de parede de Brasilia, sem fuso no texto: e o que
    esta gravado (ver `Evento.inicio`), e o `fuso` vai ao lado para quem precisar converter."""
    from app.config import FUSO
    from app.servicos.agenda import fim

    return {
        "id": registro.id,
        "titulo": registro.titulo,
        "tipo": registro.tipo,
        "descricao": registro.descricao,
        "inicio": registro.inicio.isoformat(timespec="minutes"),
        "fim": fim(registro).isoformat(timespec="minutes"),
        "fuso": FUSO,
        "duracao_min": registro.duracao_min,
        "local": registro.local,
        "conduzido_por": membro(registro.conduzido_por) if registro.conduzido_por else None,
        "criado_por_id": registro.criado_por_id,
        "criado_em": instante(registro.criado_em),
        "excluido_em": instante(registro.excluido_em),
        "ativo": registro.ativo,
        "convite": {"status": registro.google_status, "erro": registro.google_erro},
    }


def integracao_google(registro, com_email: bool = False) -> dict | None:
    """Qual conta manda os convites. O email DESTA conta aparece de proposito: o cla precisa saber
    de onde o convite vem para reconhecer o remetente. Quem conectou nao sai (e conta de pessoa, de
    fora do cla), e o token cifrado nunca sai daqui."""
    if registro is None:
        return None
    return {
        # Endereco de pessoa: so para quem administra a plataforma. Para o resto do app basta
        # saber que existe uma conta conectada.
        "email": registro.email if com_email else None,
        "conectada": True,
        "conectado_em": instante(registro.conectado_em),
    }
