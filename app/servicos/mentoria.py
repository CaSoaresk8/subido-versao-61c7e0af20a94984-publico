"""O que o rastreador faz com cada pessoa: tarefas, entregas, mentorias e o saldo de consultorias.

Nada aqui da commit, como nos outros servicos.

Toda funcao recebe o `rastreador` e a `pessoa` (o Membro) ja conferidos pelo router: a pessoa so
chega aqui se estiver num cla que este rastreador acompanha (`repo.membro_acompanhado`). E daqui
que sai o registro com o NOME dele, porque o Caio pediu transparencia com nome: quem ve uma tarefa
que nao criou, ou uma entrega que nao concluiu, precisa saber de onde veio.

Onde cada registro aparece:
  - entrega: no historico do cla, como toda entrega. E a pontuacao de um cla que mudou.
  - tarefa da mentoria, mentoria e saldo: fora do historico do cla (sao 1 para 1). A pessoa ve
    quem criou no proprio cartao e na propria area de mentoria.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.escopo import EscopoCla
from app.models import (
    A_FAZER,
    CONCLUIDO,
    CONSOME_SALDO,
    SALDO_INICIAL,
    SITUACOES_DE_MENTORIA,
    STATUS_LABEL,
    STATUS_VALIDOS,
    TIPOS_DE_MENTORIA,
    Acompanhamento,
    Membro,
    Mentoria,
    Missao,
    Rastreador,
    TarefaPessoal,
    agora,
)
from app.repositorios import entregas as repo_entregas
from app.servicos.auditoria import registrar_da_mentoria
from app.servicos.erros import FaltaResposta, ForaDeRegra, NaoEncontrado

MAXIMO_TITULO = 200
DURACAO_MINIMA = 15
DURACAO_MAXIMA = 4 * 60


def _quem(rastreador: Rastreador) -> str:
    return f"{rastreador.usuario.nome} (mentoria)"


# ---------------------------------------------------------------------------------------------
# Tarefas da mentoria
# ---------------------------------------------------------------------------------------------


def tarefa_da_mentoria(db: Session, pessoa: Membro, tarefa_id: int) -> TarefaPessoal:
    """Uma tarefa da mentoria desta pessoa, ou NaoEncontrado.

    Tarefa pessoal (criada pela propria pessoa) da o mesmo erro de tarefa que nao existe: o
    rastreador acompanha o que foi combinado, e nao le nem edita o que a pessoa anota para si.
    """
    tarefa = db.scalar(
        select(TarefaPessoal).where(
            TarefaPessoal.id == tarefa_id,
            TarefaPessoal.cla_id == pessoa.cla_id,
            TarefaPessoal.membro_id == pessoa.id,
            TarefaPessoal.criada_por_rastreador_id.is_not(None),
            TarefaPessoal.excluida_em.is_(None),
        )
    )
    if tarefa is None:
        raise NaoEncontrado("Tarefa não encontrada")
    return tarefa


def criar_tarefa(
    db: Session,
    rastreador: Rastreador,
    pessoa: Membro,
    titulo: str,
    descricao: str = "",
    prazo: date | None = None,
) -> TarefaPessoal:
    titulo = titulo.strip()[:MAXIMO_TITULO]
    if not titulo:
        raise ForaDeRegra("Escreva um título para a tarefa.")
    tarefa = TarefaPessoal(
        cla_id=pessoa.cla_id,
        membro_id=pessoa.id,
        titulo=titulo,
        descricao=descricao.strip(),
        prazo=prazo,
        status=A_FAZER,
        criada_por_rastreador_id=rastreador.id,
    )
    db.add(tarefa)
    db.flush()
    registrar_da_mentoria(
        db,
        pessoa.cla_id,
        rastreador,
        "criou",
        "tarefa",
        tarefa.id,
        f"{_quem(rastreador)} criou a tarefa '{titulo}' para {pessoa.nome}",
    )
    return tarefa


def editar_tarefa(
    db: Session,
    rastreador: Rastreador,
    pessoa: Membro,
    tarefa: TarefaPessoal,
    titulo: str,
    descricao: str,
    prazo: date | None,
    status: str,
) -> TarefaPessoal:
    titulo = titulo.strip()[:MAXIMO_TITULO]
    if not titulo:
        raise ForaDeRegra("Escreva um título para a tarefa.")
    if status not in STATUS_VALIDOS:
        raise ForaDeRegra("Status inválido.")
    mudou_status = tarefa.status != status
    tarefa.titulo = titulo
    tarefa.descricao = descricao.strip()
    tarefa.prazo = prazo
    tarefa.status = status
    # Mudar o status pelo rastreador tira o cartao de uma coluna pessoal, se estava numa: coluna
    # pessoal e da pessoa, e o status que o rastreador escolheu tem que aparecer na etapa certa.
    if mudou_status:
        tarefa.coluna_id = None
    acao = f"marcou como {STATUS_LABEL[status]}" if mudou_status else "editou"
    registrar_da_mentoria(
        db,
        pessoa.cla_id,
        rastreador,
        "atualizou",
        "tarefa",
        tarefa.id,
        f"{_quem(rastreador)} {acao} a tarefa '{titulo}' de {pessoa.nome}",
    )
    return tarefa


# ---------------------------------------------------------------------------------------------
# Entregas das missoes
# ---------------------------------------------------------------------------------------------


def salvar_entrega(
    db: Session,
    rastreador: Rastreador,
    pessoa: Membro,
    missao: Missao,
    status: str,
    resposta: str | None = None,
) -> None:
    """Muda a entrega da pessoa numa missao do cla dela. `resposta=None` mantem a que ja existe.

    A regra de "missao que exige resposta so conclui com resposta" vale tambem para o rastreador:
    ele pode preencher pela pessoa (colar o link que ela mandou no WhatsApp, por exemplo), mas nao
    pode concluir com o campo vazio. Senao o criterio do cla passaria a depender de quem clicou.
    """
    if status not in STATUS_VALIDOS:
        raise ForaDeRegra("Status inválido.")
    if missao.cla_id != pessoa.cla_id or missao.excluida_em is not None:
        raise NaoEncontrado("Missão não encontrada")

    escopo = EscopoCla(db=db, membro=pessoa)
    entrega = repo_entregas.obter_ou_criar(escopo, missao.id, pessoa.id)
    if resposta is not None:
        entrega.resposta = resposta.strip()
    if status == CONCLUIDO and missao.exige_resposta and not entrega.resposta.strip():
        raise FaltaResposta(missao)
    entrega.status = status
    entrega.concluida_em = agora() if status == CONCLUIDO else None
    # Como em `servicos/missoes.salvar_entrega`: escolher a etapa tira o cartao da coluna privada,
    # senao ele ficaria concluido num lugar que nao pontua.
    entrega.coluna_id = None
    registrar_da_mentoria(
        db,
        pessoa.cla_id,
        rastreador,
        "atualizou",
        "entrega",
        entrega.id,
        f"{_quem(rastreador)} marcou {pessoa.nome} como {STATUS_LABEL[status]} em '{missao.titulo}'",
    )


# ---------------------------------------------------------------------------------------------
# Acompanhamento, saldo e mentorias
# ---------------------------------------------------------------------------------------------


def acompanhamento(db: Session, pessoa: Membro) -> Acompanhamento:
    """O registro da pessoa na mentoria, criado com o saldo inicial na primeira vez."""
    registro = db.scalar(
        select(Acompanhamento).where(
            Acompanhamento.cla_id == pessoa.cla_id, Acompanhamento.membro_id == pessoa.id
        )
    )
    if registro is None:
        registro = Acompanhamento(
            cla_id=pessoa.cla_id,
            membro_id=pessoa.id,
            mensais_total=SALDO_INICIAL["mensal"],
            livres_total=SALDO_INICIAL["livre"],
        )
        db.add(registro)
        db.flush()
    return registro


def saldo(db: Session, pessoa: Membro) -> dict[str, dict[str, int]]:
    """Quanto a pessoa tem, usou e ainda pode marcar, por tipo. Conta feita, nunca guardada.

    Usado = mentorias que consomem saldo (marcada, realizada, faltou). Cancelada devolve.
    Pessoa sem acompanhamento ainda ve o saldo inicial, sem nada ser gravado so por olhar.
    """
    registro = db.scalar(
        select(Acompanhamento).where(
            Acompanhamento.cla_id == pessoa.cla_id, Acompanhamento.membro_id == pessoa.id
        )
    )
    totais = {
        "mensal": registro.mensais_total if registro else SALDO_INICIAL["mensal"],
        "livre": registro.livres_total if registro else SALDO_INICIAL["livre"],
    }
    usados = dict(
        db.execute(
            select(Mentoria.tipo, func.count(Mentoria.id))
            .where(
                Mentoria.cla_id == pessoa.cla_id,
                Mentoria.membro_id == pessoa.id,
                Mentoria.situacao.in_(CONSOME_SALDO),
            )
            .group_by(Mentoria.tipo)
        ).all()
    )
    return {
        tipo: {
            "total": totais[tipo],
            "usadas": usados.get(tipo, 0),
            "restam": max(0, totais[tipo] - usados.get(tipo, 0)),
        }
        for tipo in TIPOS_DE_MENTORIA
    }


def ajustar_saldo(
    db: Session, rastreador: Rastreador, pessoa: Membro, mensais: int, livres: int
) -> Acompanhamento:
    """O rastreador muda o TOTAL de cada tipo. E o caminho das excecoes (falta perdoada, bonus).

    Nao deixa o total ficar abaixo do que ja foi usado: isso deixaria o saldo negativo, que e um
    numero que ninguem sabe explicar depois.
    """
    atual = saldo(db, pessoa)
    if mensais < atual["mensal"]["usadas"] or livres < atual["livre"]["usadas"]:
        raise ForaDeRegra("O total não pode ficar abaixo do que a pessoa já usou.")
    if mensais > 100 or livres > 100:
        raise ForaDeRegra("Número alto demais para um saldo de consultorias.")
    registro = acompanhamento(db, pessoa)
    antes = (registro.mensais_total, registro.livres_total)
    registro.mensais_total = mensais
    registro.livres_total = livres
    registrar_da_mentoria(
        db,
        pessoa.cla_id,
        rastreador,
        "ajustou",
        "acompanhamento",
        registro.id,
        f"{_quem(rastreador)} ajustou o saldo de {pessoa.nome}: mensais {antes[0]} para "
        f"{mensais}, livres {antes[1]} para {livres}",
    )
    return registro


def ajustar_proprio_saldo(escopo: EscopoCla, mensais: int, livres: int) -> Acompanhamento:
    """A propria pessoa muda o total das consultorias dela. Decisao do Caio.

    Com isto o limite de 12 mais 6 deixa de ser trava e vira combinado. O que sobra de controle e a
    transparencia: o ajuste entra no registro com o nome da pessoa, e a ficha do rastreador mostra
    o historico do saldo, entao quem acompanha ve na hora que ele mudou e quem mudou.

    As mesmas duas travas do ajuste do rastreador continuam: nao desce abaixo do que ja foi usado
    (saldo negativo ninguem explica) e nao passa de 100.
    """
    from app.servicos.auditoria import registrar

    pessoa = escopo.membro
    atual = saldo(escopo.db, pessoa)
    if mensais < atual["mensal"]["usadas"] or livres < atual["livre"]["usadas"]:
        raise ForaDeRegra("O total não pode ficar abaixo do que você já usou.")
    if mensais > 100 or livres > 100 or mensais < 0 or livres < 0:
        raise ForaDeRegra("Escolha um número entre 0 e 100.")
    registro = acompanhamento(escopo.db, pessoa)
    antes = (registro.mensais_total, registro.livres_total)
    registro.mensais_total = mensais
    registro.livres_total = livres
    registrar(
        escopo,
        "ajustou",
        "acompanhamento",
        registro.id,
        f"{pessoa.nome} ajustou o próprio saldo: mensais {antes[0]} para {mensais}, "
        f"livres {antes[1]} para {livres}",
    )
    return registro


def anotar(db: Session, pessoa: Membro, texto: str) -> Acompanhamento:
    """A anotacao geral do rastreador sobre a pessoa. So ele le. Sem log: e caderno, nao acao."""
    registro = acompanhamento(db, pessoa)
    registro.anotacao = texto.strip()
    return registro


def marcar_mentoria(
    db: Session,
    rastreador: Rastreador,
    pessoa: Membro,
    tipo: str,
    inicio: datetime,
    duracao_min: int = 60,
    local: str = "",
) -> Mentoria:
    if tipo not in TIPOS_DE_MENTORIA:
        raise ForaDeRegra("Escolha o tipo da consultoria.")
    if not DURACAO_MINIMA <= duracao_min <= DURACAO_MAXIMA:
        raise ForaDeRegra("A duração vai de 15 minutos a 4 horas.")
    if len(local) > 500:
        raise ForaDeRegra("O link ou endereço ficou comprido demais.")
    if saldo(db, pessoa)[tipo]["restam"] <= 0:
        raise ForaDeRegra(
            f"{pessoa.nome} não tem mais {TIPOS_DE_MENTORIA[tipo].lower()} disponível. "
            "Se for exceção, ajuste o saldo antes."
        )
    acompanhamento(db, pessoa)  # garante o registro com o saldo inicial
    mentoria = Mentoria(
        cla_id=pessoa.cla_id,
        membro_id=pessoa.id,
        rastreador_id=rastreador.id,
        tipo=tipo,
        inicio=inicio,
        duracao_min=duracao_min,
        local=local.strip(),
    )
    db.add(mentoria)
    db.flush()
    registrar_da_mentoria(
        db,
        pessoa.cla_id,
        rastreador,
        "marcou",
        "mentoria",
        mentoria.id,
        f"{_quem(rastreador)} marcou {TIPOS_DE_MENTORIA[tipo].lower()} com {pessoa.nome} "
        f"para {inicio:%d/%m %H:%M}",
    )
    return mentoria


def mentoria_da_pessoa(db: Session, pessoa: Membro, mentoria_id: int) -> Mentoria:
    mentoria = db.scalar(
        select(Mentoria).where(
            Mentoria.id == mentoria_id,
            Mentoria.cla_id == pessoa.cla_id,
            Mentoria.membro_id == pessoa.id,
        )
    )
    if mentoria is None:
        raise NaoEncontrado("Mentoria não encontrada")
    return mentoria


def atualizar_mentoria(
    db: Session,
    rastreador: Rastreador,
    pessoa: Membro,
    mentoria: Mentoria,
    situacao: str,
    anotacao: str = "",
) -> Mentoria:
    """Muda a situacao (realizada, faltou, cancelada) e guarda o que foi tratado.

    Voltar de cancelada para marcada gasta saldo de novo, entao passa pela mesma conferencia de
    saldo que marcar do zero.
    """
    if situacao not in SITUACOES_DE_MENTORIA:
        raise ForaDeRegra("Situação inválida.")
    volta_a_consumir = mentoria.situacao not in CONSOME_SALDO and situacao in CONSOME_SALDO
    if volta_a_consumir and saldo(db, pessoa)[mentoria.tipo]["restam"] <= 0:
        raise ForaDeRegra("Sem saldo para reativar esta consultoria. Ajuste o saldo antes.")
    mudou = mentoria.situacao != situacao
    mentoria.situacao = situacao
    mentoria.anotacao = anotacao.strip()
    if mudou:
        registrar_da_mentoria(
            db,
            pessoa.cla_id,
            rastreador,
            "atualizou",
            "mentoria",
            mentoria.id,
            f"{_quem(rastreador)} marcou a consultoria de {pessoa.nome} de "
            f"{mentoria.inicio:%d/%m} como {SITUACOES_DE_MENTORIA[situacao]}",
        )
    return mentoria
