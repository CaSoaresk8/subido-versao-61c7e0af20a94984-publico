"""Dois clas no mesmo banco, e a prova de que nenhum dos dois enxerga o outro.

Isolamento nao aparece em teste que roda com um cla so: qualquer consulta parece isolada quando
existe apenas um dono possivel para cada linha. Por isso este modulo monta DOIS clas com dado em
cada um e, a partir do escopo de um, roda tudo.

Sao duas metades, porque sao duas falhas diferentes.

A primeira e a de dentro: uma funcao de repositorio que esquece o `where(cla_id)`. Aqui toda funcao
publica de `app/repositorios/` e chamada com o escopo de um cla, e o teste falha se uma unica linha
do outro aparecer no resultado. Um teste de cobertura por introspecao acompanha: funcao nova no
pacote que ninguem exercitou aqui quebra a suite, em vez de entrar sem prova nenhuma.

A segunda e a de fora: a resposta HTTP para o id alheio. Ela tem que ser 404, nunca 403. Um 403 diz
"existe, mas nao e seu", e quem esta varrendo ids quer justamente saber quais existem. Para o 404
nao ser trivial, o mesmo id e pedido tambem por quem e do outro cla, e ali tem que dar 200: sem
esse par, um id errado daria 404 por nao existir e o teste passaria sem provar nada.

As contagens dos dois clas sao deliberadamente diferentes (o cla vizinho tem mais de tudo): assim
um vazamento nao muda so o conteudo, muda o numero, e o numero e o que a assercao le.
"""

from __future__ import annotations

import inspect
import pkgutil
from datetime import date, datetime, timedelta
from importlib import import_module

import pytest
from sqlalchemy import delete, func, select

from app import repositorios
from app.models import (
    A_FAZER,
    CONCLUIDO,
    Cla,
    Coluna,
    Convite,
    DiarioEntrada,
    Entrega,
    Evento,
    Log,
    Membro,
    Missao,
    PerfilMembro,
    ResponsavelSemana,
    TarefaPessoal,
    Usuario,
    agora,
)
from app.repositorios import colunas as repo_colunas
from app.repositorios import convites as repo_convites
from app.repositorios import diario as repo_diario
from app.repositorios import entregas as repo_entregas
from app.repositorios import eventos as repo_eventos
from app.repositorios import logs as repo_logs
from app.repositorios import membros as repo_membros
from app.repositorios import missoes as repo_missoes
from app.repositorios import tarefas as repo_tarefas
from app.servicos.auditoria import registrar
from app.servicos.calendario import eventos_do_cla
from app.servicos.ranking import numeros_do_cla, quem_fez_cada_missao, ranking
from tests import fabrica

# O inventario de funcoes que este modulo garante. Duas listas, porque sao dois contratos: o de
# cima e exercitado com dois clas no banco; o de baixo declara as excecoes, que rodam antes de
# existir cla ativo (login, escolha de cla, convite) e por isso nao recebem escopo nenhum.
ESCOPADAS = {
    "colunas": {"do_membro", "por_id", "maior_ordem"},
    "convites": {"do_cla", "por_id"},
    "entregas": {
        "do_membro",
        "de_missoes_ativas",
        "pontuacao_concluida",
        "obter_ou_criar",
        "na_coluna",
    },
    "diario": {
        "responsavel_da_semana",
        "entradas_da_semana",
        "ultimas_entradas",
        "historico_da_pessoa",
        "perfil",
    },
    "eventos": {
        "ativos",
        "futuros",
        "do_periodo",
        "na_lixeira",
        "por_id",
        "emails_dos_membros",
    },
    "logs": {"recentes"},
    "membros": {"todos", "total", "nomes", "por_id"},
    "missoes": {"ativas", "na_lixeira", "por_id"},
    "tarefas": {"do_membro", "na_lixeira_do_membro", "por_id", "na_coluna"},
}
SEM_ESCOPO = {
    "contas": {
        "usuario_por_email",
        "usuario_por_id",
        "membro_por_id",
        "membros_do_usuario",
        "membro_do_usuario_no_cla",
        "cla_por_id",
        "convite_por_token",
    },
    # O rastreador atravessa clas de proposito: e o papel da mentoria. O recorte dele nao e o cla
    # da sessao, e a lista de clas que ele escolheu, e cada funcao daqui recebe o rastreador e
    # filtra por essa lista. Quem prova esse recorte e tests/test_rastreador.py, que monta dois
    # clas e confere que o de fora da lista responde 404.
    "rastreadores": {
        "por_usuario",
        "todos",
        "ids_dos_clas",
        "clas_acompanhados",
        "clas_para_escolher",
        "acompanha",
        "membro_acompanhado",
        "pessoas",
        "email_do_membro",
        "convite_por_token",
        "convites",
        "vale",
        # Estas recebem a PESSOA (o Membro) ja conferida pelo router, e filtram pelo cla dela.
        "tarefas_da_mentoria",
        "mentorias_da_pessoa",
        "acompanhamento_da_pessoa",
        "nomes_de_rastreadores",
        "historico_do_saldo",
    },
    # A conta Google e UMA para a plataforma inteira e nao tem cla_id. A lista de eventos futuros de
    # todos os clas so e usada para sincronizar cada evento com o escopo do proprio cla
    # (servicos/agenda.sincronizar_todos), e nenhuma tela a mostra.
    "plataforma": {"integracao_google", "futuros_de_todos_os_clas"},
}

# Strings que so existem no cla vizinho. Se uma delas aparecer numa tela do outro cla, vazou.
SECRETOS = [
    "Cla Vizinho",
    "Missao secreta do vizinho",
    "Gaveta secreta",
    "Tarefa secreta",
    "Bia",
    "Workshop do vizinho",
]


def _missao(cla_id: int, autor_id: int, titulo: str, pontos: int, **extra) -> Missao:
    return Missao(
        cla_id=cla_id,
        titulo=titulo,
        descricao="",
        pontos=pontos,
        criada_por_id=autor_id,
        **extra,
    )


def _convite(cla_id: int, autor_id: int, token: str) -> Convite:
    return Convite(
        cla_id=cla_id,
        token=token,
        criado_por_id=autor_id,
        expira_em=agora() + timedelta(days=7),
    )


@pytest.fixture(scope="module")
def dois_clas():
    """Cla A com duas pessoas e cla B com tres, cada um com dado em todas as tabelas.

    Tudo em banco proprio do modulo, com os PRAGMAs do app: sem `foreign_keys=ON` as FKs compostas
    (cla_id, membro_id) ficam desligadas, e sao elas a segunda metade da garantia de isolamento.
    """
    with fabrica.banco("isolamento") as (Sessao, _engine):
        with Sessao() as db:
            cla_a = fabrica.criar_cla(db, "Cla A")
            ana = fabrica.entrar(db, cla_a, "Ana", "ana@a.com")
            alex = fabrica.entrar(db, cla_a, "Alex", "alex@a.com")

            cla_b = fabrica.criar_cla(db, "Cla Vizinho")
            bia = fabrica.entrar(db, cla_b, "Bia", "bia@b.com")
            beto = fabrica.entrar(db, cla_b, "Beto", "beto@b.com")
            bento = fabrica.entrar(db, cla_b, "Bento", "bento@b.com")

            ma1 = _missao(cla_a.id, ana.id, "Resumo do curso", 100, vencimento=date(2026, 9, 30))
            ma2 = _missao(cla_a.id, ana.id, "Prova", 50)
            ma_lixo = _missao(cla_a.id, ana.id, "Missao descartada", 70)
            col_a = Coluna(cla_id=cla_a.id, membro_id=ana.id, nome="Gaveta da Ana", ordem=1)

            mb1 = _missao(cla_b.id, bia.id, "Missao secreta do vizinho", 200)
            mb2 = _missao(cla_b.id, bia.id, "Segunda do vizinho", 300)
            mb3 = _missao(cla_b.id, bia.id, "Terceira do vizinho", 400)
            mb_lixo1 = _missao(cla_b.id, bia.id, "Descartada do vizinho", 10)
            mb_lixo2 = _missao(cla_b.id, bia.id, "Outra descartada do vizinho", 20)
            col_b = Coluna(cla_id=cla_b.id, membro_id=bia.id, nome="Gaveta secreta", ordem=5)
            col_b2 = Coluna(cla_id=cla_b.id, membro_id=bia.id, nome="Outra gaveta secreta", ordem=9)

            db.add_all([ma1, ma2, ma_lixo, col_a, mb1, mb2, mb3, mb_lixo1, mb_lixo2, col_b, col_b2])
            db.flush()
            ma_lixo.excluida_em = agora()
            mb_lixo1.excluida_em = agora()
            mb_lixo2.excluida_em = agora()

            ta1 = TarefaPessoal(
                cla_id=cla_a.id,
                membro_id=ana.id,
                titulo="So da Ana",
                status=A_FAZER,
                coluna_id=col_a.id,
                prazo=date(2026, 9, 25),
            )
            ta_lixo = TarefaPessoal(
                cla_id=cla_a.id, membro_id=ana.id, titulo="Tarefa descartada", status=A_FAZER
            )
            tb1 = TarefaPessoal(
                cla_id=cla_b.id,
                membro_id=bia.id,
                titulo="Tarefa secreta",
                status=A_FAZER,
                coluna_id=col_b.id,
                prazo=date(2026, 9, 25),
            )
            tb2 = TarefaPessoal(
                cla_id=cla_b.id, membro_id=bia.id, titulo="Outra tarefa secreta", status=A_FAZER
            )
            tb_lixo = TarefaPessoal(
                cla_id=cla_b.id, membro_id=bia.id, titulo="Descartada secreta", status=A_FAZER
            )
            db.add_all([ta1, ta_lixo, tb1, tb2, tb_lixo])
            db.flush()
            ta_lixo.excluida_em = agora()
            tb_lixo.excluida_em = agora()

            db.add_all(
                [
                    # Cla A: 100 pontos gerados, numa entrega. A da ma2 esta em coluna privada, e
                    # cartao guardado em gaveta nao pontua.
                    Entrega(cla_id=cla_a.id, missao_id=ma1.id, membro_id=ana.id, status=CONCLUIDO),
                    Entrega(
                        cla_id=cla_a.id,
                        missao_id=ma2.id,
                        membro_id=ana.id,
                        status=A_FAZER,
                        coluna_id=col_a.id,
                    ),
                    Entrega(cla_id=cla_a.id, missao_id=ma1.id, membro_id=alex.id, status=A_FAZER),
                    # Cla B: 700 pontos gerados, em tres entregas. Numero diferente de proposito.
                    Entrega(cla_id=cla_b.id, missao_id=mb1.id, membro_id=bia.id, status=CONCLUIDO),
                    Entrega(cla_id=cla_b.id, missao_id=mb2.id, membro_id=bia.id, status=CONCLUIDO),
                    Entrega(cla_id=cla_b.id, missao_id=mb1.id, membro_id=beto.id, status=CONCLUIDO),
                    Entrega(cla_id=cla_b.id, missao_id=mb3.id, membro_id=bento.id, status=A_FAZER),
                    Entrega(
                        cla_id=cla_b.id,
                        missao_id=mb3.id,
                        membro_id=bia.id,
                        status=A_FAZER,
                        coluna_id=col_b.id,
                    ),
                    _convite(cla_a.id, ana.id, "token-do-cla-a"),
                    _convite(cla_b.id, bia.id, "token-do-cla-b-1"),
                    _convite(cla_b.id, bia.id, "token-do-cla-b-2"),
                ]
            )

            # Agenda: um evento vivo e um na lixeira no A; dois vivos e um na lixeira no B.
            # Numeros diferentes pelo mesmo motivo das missoes.
            futuro = datetime(2099, 1, 10, 20, 0)
            ea1 = Evento(
                cla_id=cla_a.id, titulo="Reuniao do A", inicio=futuro, criado_por_id=ana.id
            )
            ea_lixo = Evento(
                cla_id=cla_a.id,
                titulo="Reuniao descartada",
                inicio=futuro,
                criado_por_id=ana.id,
                excluido_em=agora(),
            )
            eb1 = Evento(
                cla_id=cla_b.id,
                titulo="Workshop secreto",
                inicio=futuro,
                criado_por_id=bia.id,
                conduzido_por_id=beto.id,
            )
            eb2 = Evento(
                cla_id=cla_b.id, titulo="Outro secreto", inicio=futuro, criado_por_id=bia.id
            )
            eb_lixo = Evento(
                cla_id=cla_b.id,
                titulo="Descartado secreto",
                inicio=futuro,
                criado_por_id=bia.id,
                excluido_em=agora(),
            )
            db.add_all([ea1, ea_lixo, eb1, eb2, eb_lixo])
            db.flush()

            # Acompanhamento: na mesma semana, uma conversa no A e duas no B, um responsavel e um
            # perfil em cada. Se o B vazar para o A, a contagem do A muda.
            semana = date(2099, 1, 5)
            db.add_all(
                [
                    ResponsavelSemana(cla_id=cla_a.id, semana=semana, membro_id=ana.id),
                    ResponsavelSemana(cla_id=cla_b.id, semana=semana, membro_id=bia.id),
                    DiarioEntrada(
                        cla_id=cla_a.id,
                        membro_id=alex.id,
                        semana=semana,
                        autor_id=ana.id,
                        status="em_dia",
                    ),
                    DiarioEntrada(
                        cla_id=cla_b.id,
                        membro_id=beto.id,
                        semana=semana,
                        autor_id=bia.id,
                        status="travado",
                        como_esta="Dificuldade secreta",
                    ),
                    DiarioEntrada(
                        cla_id=cla_b.id,
                        membro_id=bento.id,
                        semana=semana,
                        autor_id=bia.id,
                        status="atencao",
                    ),
                    PerfilMembro(cla_id=cla_a.id, membro_id=ana.id, metas="Meta da Ana"),
                    PerfilMembro(cla_id=cla_b.id, membro_id=bia.id, metas="Meta secreta"),
                ]
            )
            db.flush()

            escopo_a = fabrica.escopo(db, ana)
            escopo_b = fabrica.escopo(db, bia)
            registrar(escopo_a, "criou", "missao", ma1.id, "Resumo do curso")
            for titulo in (
                "Missao secreta do vizinho",
                "Segunda do vizinho",
                "Terceira do vizinho",
            ):
                registrar(escopo_b, "criou", "missao", mb1.id, titulo)
            db.commit()

            yield {
                "a": {
                    "escopo": escopo_a,
                    "cla_id": cla_a.id,
                    "membro_id": ana.id,
                    "coluna_id": col_a.id,
                    "missao_id": ma1.id,
                    "missao_lixeira_id": ma_lixo.id,
                    "tarefa_id": ta1.id,
                    "evento_id": ea1.id,
                    "acompanhado_id": alex.id,
                    "convite_id": db.scalar(select(Convite.id).where(Convite.cla_id == cla_a.id)),
                },
                "b": {
                    "escopo": escopo_b,
                    "cla_id": cla_b.id,
                    "membro_id": bia.id,
                    "coluna_id": col_b.id,
                    "missao_id": mb1.id,
                    "missao_lixeira_id": mb_lixo1.id,
                    "tarefa_id": tb1.id,
                    "evento_id": eb1.id,
                    "acompanhado_id": beto.id,
                    "convite_id": db.scalar(select(Convite.id).where(Convite.cla_id == cla_b.id)),
                },
            }


def _chamar_tudo(lado: dict) -> dict[str, object]:
    """Toda funcao publica de repositorio, chamada com o escopo e os ids do proprio cla.

    As chaves sao "modulo.funcao" e e por elas que o teste de cobertura confere que nenhuma funcao
    do pacote ficou de fora. Por isso a chamada vive aqui e nao espalhada nos testes: existe um
    lugar so onde "esta coberta" quer dizer "foi chamada de verdade".
    """
    escopo = lado["escopo"]
    membro_id, coluna_id, missao_id = lado["membro_id"], lado["coluna_id"], lado["missao_id"]
    return {
        "colunas.do_membro": repo_colunas.do_membro(escopo, membro_id),
        "colunas.por_id": repo_colunas.por_id(escopo, coluna_id),
        "colunas.maior_ordem": repo_colunas.maior_ordem(escopo, membro_id),
        "convites.do_cla": repo_convites.do_cla(escopo),
        "convites.por_id": repo_convites.por_id(escopo, lado["convite_id"]),
        "entregas.do_membro": repo_entregas.do_membro(escopo, membro_id),
        "entregas.de_missoes_ativas": repo_entregas.de_missoes_ativas(escopo),
        "entregas.pontuacao_concluida": repo_entregas.pontuacao_concluida(escopo),
        "entregas.obter_ou_criar": repo_entregas.obter_ou_criar(escopo, missao_id, membro_id),
        "entregas.na_coluna": repo_entregas.na_coluna(escopo, coluna_id),
        "diario.responsavel_da_semana": repo_diario.responsavel_da_semana(escopo, date(2099, 1, 5)),
        "diario.entradas_da_semana": repo_diario.entradas_da_semana(escopo, date(2099, 1, 5)),
        "diario.ultimas_entradas": repo_diario.ultimas_entradas(escopo),
        "diario.historico_da_pessoa": repo_diario.historico_da_pessoa(
            escopo, lado["acompanhado_id"]
        ),
        "diario.perfil": repo_diario.perfil(escopo, membro_id),
        "eventos.ativos": repo_eventos.ativos(escopo),
        "eventos.futuros": repo_eventos.futuros(escopo, datetime(2026, 1, 1)),
        "eventos.do_periodo": repo_eventos.do_periodo(
            escopo, datetime(2099, 1, 1), datetime(2099, 2, 1)
        ),
        "eventos.na_lixeira": repo_eventos.na_lixeira(escopo),
        "eventos.por_id": repo_eventos.por_id(escopo, lado["evento_id"]),
        "eventos.emails_dos_membros": repo_eventos.emails_dos_membros(escopo),
        "logs.recentes": repo_logs.recentes(escopo),
        "membros.todos": repo_membros.todos(escopo),
        "membros.total": repo_membros.total(escopo),
        "membros.nomes": repo_membros.nomes(escopo),
        "membros.por_id": repo_membros.por_id(escopo, membro_id),
        "missoes.ativas": repo_missoes.ativas(escopo, com_entregas=True),
        "missoes.na_lixeira": repo_missoes.na_lixeira(escopo),
        "missoes.por_id": repo_missoes.por_id(escopo, missao_id),
        "tarefas.do_membro": repo_tarefas.do_membro(escopo, membro_id),
        "tarefas.na_lixeira_do_membro": repo_tarefas.na_lixeira_do_membro(escopo, membro_id),
        "tarefas.por_id": repo_tarefas.por_id(escopo, lado["tarefa_id"]),
        "tarefas.na_coluna": repo_tarefas.na_coluna(escopo, coluna_id),
    }


def _linhas(valor) -> list:
    """As linhas do banco que estao dentro de um resultado, seja ele qual for.

    Os repositorios devolvem lista, dicionario indexado, objeto solto, None, inteiro e tupla de
    inteiros. O que interessa em todos e o mesmo: as linhas com cla_id que sairam do banco.
    """
    if valor is None or isinstance(valor, (int, str)):
        return []
    if isinstance(valor, dict):
        valor = list(valor.values())
    if isinstance(valor, (list, tuple, set)):
        return [item for parte in valor for item in _linhas(parte)]
    return [valor] if hasattr(valor, "cla_id") else []


@pytest.mark.parametrize("lado", ["a", "b"])
def test_nenhuma_funcao_de_repositorio_devolve_linha_de_outro_cla(dois_clas, lado):
    meu = dois_clas[lado]
    for nome, resultado in _chamar_tudo(meu).items():
        linhas = _linhas(resultado)
        invasoras = [linha for linha in linhas if linha.cla_id != meu["cla_id"]]
        assert not invasoras, (
            f"{nome} devolveu {len(invasoras)} linha(s) de outro cla: "
            f"{[(type(x).__name__, x.id, x.cla_id) for x in invasoras]}"
        )


@pytest.mark.parametrize("lado", ["a", "b"])
def test_toda_funcao_de_repositorio_devolve_alguma_coisa(dois_clas, lado):
    """Resultado vazio passaria no teste de cima sem provar nada. Aqui nada pode vir vazio."""
    for nome, resultado in _chamar_tudo(dois_clas[lado]).items():
        if nome == "entregas.pontuacao_concluida":
            continue  # tupla de inteiros, conferida nos numeros exatos abaixo
        assert resultado, f"{nome} devolveu vazio: o cenario nao cobre essa funcao"


def test_o_convite_da_agenda_so_leva_email_do_proprio_cla(dois_clas):
    """`emails_dos_membros` devolve texto, nao linha com cla_id, entao o teste generico de cima nao
    o enxerga. E e justamente o que vai para fora: um email do cla B aqui seria um convite de
    reuniao do cla A chegando na caixa de quem nunca entrou nele."""
    assert repo_eventos.emails_dos_membros(dois_clas["a"]["escopo"]) == ["alex@a.com", "ana@a.com"]
    assert repo_eventos.emails_dos_membros(dois_clas["b"]["escopo"]) == [
        "bento@b.com",
        "beto@b.com",
        "bia@b.com",
    ]
    for lado, esperado in (("a", ["Reuniao do A"]), ("b", ["Workshop secreto", "Outro secreto"])):
        titulos = [e.titulo for e in repo_eventos.ativos(dois_clas[lado]["escopo"])]
        assert sorted(titulos) == sorted(esperado)


def test_cada_cla_ve_exatamente_os_seus_numeros(dois_clas):
    """Os dois clas tem contagens diferentes: vazamento nao muda so o conteudo, muda o numero."""
    a, b = _chamar_tudo(dois_clas["a"]), _chamar_tudo(dois_clas["b"])

    assert (len(a["membros.todos"]), a["membros.total"], len(a["membros.nomes"])) == (2, 2, 2)
    assert (len(b["membros.todos"]), b["membros.total"], len(b["membros.nomes"])) == (3, 3, 3)

    assert (len(a["missoes.ativas"]), len(a["missoes.na_lixeira"])) == (2, 1)
    assert (len(b["missoes.ativas"]), len(b["missoes.na_lixeira"])) == (3, 2)

    assert (len(a["entregas.de_missoes_ativas"]), a["entregas.pontuacao_concluida"]) == (
        3,
        (100, 1),
    )
    assert (len(b["entregas.de_missoes_ativas"]), b["entregas.pontuacao_concluida"]) == (
        5,
        (700, 3),
    )

    assert (len(a["colunas.do_membro"]), a["colunas.maior_ordem"]) == (1, 1)
    assert (len(b["colunas.do_membro"]), b["colunas.maior_ordem"]) == (2, 9)

    assert (len(a["tarefas.do_membro"]), len(a["tarefas.na_lixeira_do_membro"])) == (1, 1)
    assert (len(b["tarefas.do_membro"]), len(b["tarefas.na_lixeira_do_membro"])) == (2, 1)

    assert (len(a["convites.do_cla"]), len(a["logs.recentes"])) == (1, 1)
    assert (len(b["convites.do_cla"]), len(b["logs.recentes"])) == (2, 3)


def test_id_do_outro_cla_e_o_mesmo_que_id_que_nao_existe(dois_clas):
    """`escopo.obter` devolve None para os dois casos, e e o que faz o router responder um 404 so."""
    a, b = dois_clas["a"], dois_clas["b"]
    escopo = a["escopo"]
    assert repo_missoes.por_id(escopo, b["missao_id"]) is None
    assert repo_missoes.por_id(escopo, b["missao_lixeira_id"]) is None
    assert repo_colunas.por_id(escopo, b["coluna_id"]) is None
    assert repo_tarefas.por_id(escopo, b["tarefa_id"]) is None
    assert repo_convites.por_id(escopo, b["convite_id"]) is None
    assert repo_membros.por_id(escopo, b["membro_id"]) is None
    assert repo_missoes.por_id(escopo, 99999) is None


def test_membro_do_outro_cla_nao_tem_nada_no_meu(dois_clas):
    """As funcoes que recebem membro_id: passar o id de alguem do cla vizinho nao abre porta."""
    escopo, alheio = dois_clas["a"]["escopo"], dois_clas["b"]["membro_id"]
    assert repo_colunas.do_membro(escopo, alheio) == []
    assert repo_colunas.maior_ordem(escopo, alheio) == 0
    assert repo_tarefas.do_membro(escopo, alheio) == []
    assert repo_tarefas.na_lixeira_do_membro(escopo, alheio) == []
    assert repo_entregas.do_membro(escopo, alheio) == {}


def test_coluna_do_outro_cla_nao_arrasta_cartao_nenhum(dois_clas):
    """Coluna alheia como filtro: mesmo com o id certo, nao ha cartao do meu cla dentro dela."""
    escopo, coluna_alheia = dois_clas["a"]["escopo"], dois_clas["b"]["coluna_id"]
    assert repo_entregas.na_coluna(escopo, coluna_alheia) == []
    assert repo_tarefas.na_coluna(escopo, coluna_alheia) == []


def test_as_telas_do_dashboard_nao_misturam_os_dois_clas(dois_clas):
    """O que a rota GET / monta: ranking, numeros, grafico e calendario, um cla por vez."""
    for lado in ("a", "b"):
        meu = dois_clas[lado]
        escopo = meu["escopo"]
        missoes = repo_missoes.ativas(escopo, com_entregas=True)
        linhas = ranking(escopo, missoes)
        numeros = numeros_do_cla(escopo, missoes)
        barras = quem_fez_cada_missao(escopo, missoes)
        eventos = eventos_do_cla(escopo, missoes, escopo.membro_id)

        assert {linha["membro"].cla_id for linha in linhas} == {meu["cla_id"]}
        assert numeros["total_membros"] == len(linhas)
        assert sum(linha["pontos"] for linha in linhas) == numeros["pontos_gerados"]
        assert sum(barra["quantidade"] for barra in barras) == numeros["entregas_concluidas"]
        assert {barra["missao"].cla_id for barra in barras} == {meu["cla_id"]}
        ids_das_tarefas = {t.id for t in repo_tarefas.do_membro(escopo, escopo.membro_id)}
        for dia in eventos.values():
            for evento in dia:
                if evento["tipo"] == "pessoal":
                    assert evento["id"] in ids_das_tarefas

    a, b = dois_clas["a"], dois_clas["b"]
    numeros_a = numeros_do_cla(a["escopo"], repo_missoes.ativas(a["escopo"], com_entregas=True))
    numeros_b = numeros_do_cla(b["escopo"], repo_missoes.ativas(b["escopo"], com_entregas=True))
    assert (numeros_a["pontos_gerados"], numeros_a["entregas_concluidas"]) == (100, 1)
    assert (numeros_b["pontos_gerados"], numeros_b["entregas_concluidas"]) == (700, 3)


def _publicas(modulo) -> set[str]:
    """Funcoes definidas NO modulo, sem as importadas de fora e sem as privadas."""
    return {
        nome
        for nome, funcao in inspect.getmembers(modulo, inspect.isfunction)
        if not nome.startswith("_") and funcao.__module__ == modulo.__name__
    }


def test_nenhuma_funcao_de_repositorio_escapa_deste_modulo():
    """Funcao nova em app/repositorios/ quebra aqui, em vez de entrar sem prova de isolamento.

    E o ponto do teste inteiro: a garantia nao pode valer so para o que existia no dia em que ele
    foi escrito. Quem acrescentar uma consulta escolhe entre exercita-la em `_chamar_tudo` ou
    declara-la em SEM_ESCOPO dizendo por que ela roda fora de cla.
    """
    encontradas = {}
    for info in pkgutil.iter_modules(repositorios.__path__):
        modulo = import_module(f"{repositorios.__name__}.{info.name}")
        encontradas[info.name] = _publicas(modulo)

    declaradas = {**ESCOPADAS, **SEM_ESCOPO}
    # A diferenca e calculada funcao por funcao, e nao modulo por modulo: o caso comum e alguem
    # acrescentar uma consulta num modulo que ja existe, e ai os dois dicionarios tem as mesmas
    # chaves. Comparar so as chaves daria uma mensagem dizendo "faltando []" com o teste vermelho.
    faltando = sorted(
        f"{modulo}.{funcao}"
        for modulo, funcoes in encontradas.items()
        for funcao in funcoes - declaradas.get(modulo, set())
    )
    sobrando = sorted(
        f"{modulo}.{funcao}"
        for modulo, funcoes in declaradas.items()
        for funcao in funcoes - encontradas.get(modulo, set())
    )
    assert not (faltando or sobrando), (
        "o inventario deste teste nao bate com app/repositorios/: "
        f"existe no pacote e nao esta declarado aqui {faltando}; "
        f"esta declarado aqui e nao existe mais no pacote {sobrando}"
    )


def test_a_lista_de_chamadas_cobre_todas_as_escopadas(dois_clas):
    """O elo seguinte: estar no inventario nao basta, tem que ter sido chamada de verdade.

    Sem esta assercao, acrescentar o nome em ESCOPADAS ja calaria o teste de cima, e a funcao nova
    passaria a constar como coberta sem nunca ter rodado com dois clas no banco.
    """
    chamadas = set(_chamar_tudo(dois_clas["a"]))
    esperadas = {
        f"{modulo}.{funcao}" for modulo, funcoes in ESCOPADAS.items() for funcao in funcoes
    }
    assert chamadas == esperadas


# ----------------------------------------------------------------------------------------------
# A metade de fora: o que o HTTP responde para o id do outro cla.
# ----------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cla_vizinho(app_web, ana, bruno):  # noqa: ARG001
    """Um segundo cla no banco do app, com dado proprio, apagado na saida do modulo.

    Depende de `ana` e `bruno` de proposito, e nao por acidente de ordem alfabetica de arquivo: o
    Bruno entra por um convite que a Ana gera, entao as duas contas tem que existir antes de
    qualquer outro cla aparecer no banco. Pedir as fixtures aqui e o que garante essa ordem.

    A limpeza no fim e obrigatoria: este e o banco compartilhado da suite de ponta a ponta, e as
    contagens de test_fluxo leem ranking e grafico. Teste que deixa cla para tras mente na rodada
    seguinte.
    """
    from fastapi.testclient import TestClient

    from app.database import SessionLocal
    from app.servicos import contas as servico_contas

    db = SessionLocal()
    cla = Cla(nome="Cla Vizinho")
    db.add(cla)
    db.flush()
    usuario = servico_contas.criar_usuario(
        db, "Bia Vizinha", "bia@vizinho.com", "senhaforte1", "11911110001"
    )
    bia = servico_contas.entrar_no_cla(db, usuario, cla)

    missao = _missao(cla.id, bia.id, "Missao secreta do vizinho", 200)
    missao_lixo = _missao(cla.id, bia.id, "Descartada do vizinho", 50)
    coluna = Coluna(cla_id=cla.id, membro_id=bia.id, nome="Gaveta secreta", ordem=1)
    db.add_all([missao, missao_lixo, coluna])
    db.flush()
    missao_lixo.excluida_em = agora()

    tarefa = TarefaPessoal(cla_id=cla.id, membro_id=bia.id, titulo="Tarefa secreta", status=A_FAZER)
    tarefa_lixo = TarefaPessoal(
        cla_id=cla.id, membro_id=bia.id, titulo="Descartada secreta", status=A_FAZER
    )
    db.add_all([tarefa, tarefa_lixo])
    db.flush()
    tarefa_lixo.excluida_em = agora()
    evento = Evento(
        cla_id=cla.id,
        titulo="Workshop do vizinho",
        inicio=datetime(2099, 1, 10, 20, 0),
        criado_por_id=bia.id,
    )
    evento_lixo = Evento(
        cla_id=cla.id,
        titulo="Workshop descartado do vizinho",
        inicio=datetime(2099, 1, 11, 20, 0),
        criado_por_id=bia.id,
        excluido_em=agora(),
    )
    db.add_all([evento, evento_lixo])
    db.flush()
    db.commit()

    dados = {
        "cla_id": cla.id,
        "membro_id": bia.id,
        "missao_id": missao.id,
        "missao_lixeira_id": missao_lixo.id,
        "coluna_id": coluna.id,
        "tarefa_id": tarefa.id,
        "tarefa_lixeira_id": tarefa_lixo.id,
        "evento_id": evento.id,
        "evento_lixeira_id": evento_lixo.id,
    }

    cliente = TestClient(app_web)
    entrada = cliente.post(
        "/login", data={"email": "bia@vizinho.com", "senha": "senhaforte1"}, follow_redirects=False
    )
    assert entrada.status_code == 303, "a Bia precisa entrar: sem isso o 404 do outro lado e vazio"
    dados["cliente"] = cliente

    try:
        yield dados
    finally:
        # A ordem e a das FKs, de dentro para fora: missao aponta para o membro que a criou, e
        # membro aponta para o cla. Com PRAGMA foreign_keys=ON, inverter isso estoura no DELETE.
        usuario_id = usuario.id
        for modelo in (
            Log,
            Evento,
            Entrega,
            TarefaPessoal,
            Coluna,
            Convite,
            Missao,
            Membro,
        ):
            db.execute(delete(modelo).where(modelo.cla_id == cla.id))
        db.execute(delete(Cla).where(Cla.id == cla.id))
        db.execute(delete(Usuario).where(Usuario.id == usuario_id))
        db.commit()
        db.close()


def _pedidos_com_id_alheio(vizinho: dict) -> list[tuple[str, str, dict]]:
    """Todo endpoint que recebe id de recurso, com o id do cla vizinho no lugar."""
    missao, lixo = vizinho["missao_id"], vizinho["missao_lixeira_id"]
    tarefa, tarefa_lixo = vizinho["tarefa_id"], vizinho["tarefa_lixeira_id"]
    coluna = vizinho["coluna_id"]
    evento, evento_lixo = vizinho["evento_id"], vizinho["evento_lixeira_id"]
    return [
        ("GET", f"/agenda/{evento}", {}),
        ("GET", f"/agenda/{evento}/editar", {}),
        (
            "POST",
            f"/agenda/{evento}/editar",
            {"titulo": "invadido", "inicio": "2099-01-10T20:00", "tipo": "reuniao"},
        ),
        ("POST", f"/agenda/{evento}/excluir", {}),
        ("POST", f"/agenda/{evento}/reenviar", {}),
        ("POST", f"/historico/eventos/{evento_lixo}/restaurar", {}),
        ("GET", f"/missoes/{missao}", {}),
        ("GET", f"/missoes/{missao}/editar", {}),
        ("POST", f"/missoes/{missao}/editar", {"titulo": "invadido"}),
        ("POST", f"/missoes/{missao}/excluir", {}),
        ("POST", f"/missoes/{missao}/entrega", {"status": CONCLUIDO}),
        ("POST", f"/historico/missoes/{lixo}/restaurar", {}),
        ("POST", f"/historico/tarefas/{tarefa_lixo}/restaurar", {}),
        ("POST", f"/minhas/tarefas/{tarefa}/editar", {"titulo": "invadido"}),
        ("POST", f"/minhas/tarefas/{tarefa}/excluir", {}),
        ("POST", f"/minhas/colunas/{coluna}/excluir", {}),
    ]


def test_id_do_outro_cla_responde_404_e_nunca_403(ana, cla_vizinho):
    """404 e a unica resposta aceitavel. 403 confirmaria que o id existe, que e meia resposta."""
    for metodo, url, dados in _pedidos_com_id_alheio(cla_vizinho):
        resposta = (
            ana.get(url, follow_redirects=False)
            if metodo == "GET"
            else ana.post(url, data=dados, follow_redirects=False)
        )
        assert resposta.status_code == 404, (
            f"{metodo} {url} respondeu {resposta.status_code}: id de outro cla tem que ser 404"
        )


def test_o_404_nao_e_de_id_inexistente(cla_vizinho):
    """A prova de que os ids acima existem: para quem e do cla deles, a mesma URL abre.

    Sem este par, um id errado no teste daria 404 por nao existir e a suite passaria verde sem ter
    exercitado isolamento nenhum.
    """
    bia = cla_vizinho["cliente"]
    assert bia.get(f"/missoes/{cla_vizinho['missao_id']}").status_code == 200
    assert bia.get(f"/missoes/{cla_vizinho['missao_id']}/editar").status_code == 200
    historico = bia.get("/historico")
    assert historico.status_code == 200
    assert "Descartada do vizinho" in historico.text
    assert "Descartada secreta" in historico.text
    assert bia.get(f"/agenda/{cla_vizinho['evento_id']}").status_code == 200
    assert "Workshop descartado do vizinho" in historico.text


# O cartao que vai no pedido abaixo. Nao e o de ninguem, e isso e o ponto: `resolver_destino` roda
# ANTES de `colocar`, entao o destino ja foi recusado quando a chave seria lida. Antes aqui estava
# "missao-1", que hoje e uma missao de outro modulo de teste: inerte por sorte, porque a ordem das
# duas chamadas a mantem fora do caminho. Sorte que depende da ordem interna de um servico nao e
# garantia, e o dia em que essa ordem invertesse este teste passaria a mexer numa missao alheia de
# verdade, do lado de dentro de um teste que existe para provar que isso nao acontece.
CARTAO_QUE_NAO_EXISTE = "missao-987654"


def test_destino_de_coluna_alheia_e_indistinguivel_de_coluna_que_nao_existe(ana, cla_vizinho):
    """Arrastar para a gaveta de outro cla: mesmo codigo e mesmo corpo de um id inventado.

    Um destino aceito por engano daria 303 (o redirect de volta para o quadro), e nao 400, entao a
    assercao continua vendo a falha que ela existe para ver mesmo com a chave inerte.
    """
    alheia = ana.post(
        "/minhas/mover-form",
        data={"chave": CARTAO_QUE_NAO_EXISTE, "destino": f"c{cla_vizinho['coluna_id']}"},
        follow_redirects=False,
    )
    inventada = ana.post(
        "/minhas/mover-form",
        data={"chave": CARTAO_QUE_NAO_EXISTE, "destino": "c987654"},
        follow_redirects=False,
    )
    assert alheia.status_code == inventada.status_code == 400
    assert alheia.text == inventada.text


def test_nenhuma_tela_da_ana_cita_o_cla_vizinho(ana, cla_vizinho):  # noqa: ARG001
    for url in ("/", "/missoes", "/minhas", "/historico", "/agenda", "/?ano=2099&mes=1"):
        texto = ana.get(url).text
        for secreto in SECRETOS:
            assert secreto not in texto, f"{url} mostrou '{secreto}', que e do outro cla"


def test_o_pedido_recusado_nao_deixou_marca_no_outro_cla(ana, cla_vizinho):
    """404 depois do estrago nao vale: o POST recusado nao pode ter escrito nada.

    Roda depois do sweep de propostito (as funcoes acima ja mandaram editar, excluir, restaurar e
    concluir), e le o banco direto para conferir que nada disso aconteceu.
    """
    from app.database import SessionLocal

    for metodo, url, dados in _pedidos_com_id_alheio(cla_vizinho):
        if metodo == "POST":
            ana.post(url, data=dados, follow_redirects=False)

    cla_id = cla_vizinho["cla_id"]
    with SessionLocal() as db:
        missao = db.get(Missao, cla_vizinho["missao_id"])
        tarefa = db.get(TarefaPessoal, cla_vizinho["tarefa_id"])
        tarefa_lixo = db.get(TarefaPessoal, cla_vizinho["tarefa_lixeira_id"])
        missao_lixo = db.get(Missao, cla_vizinho["missao_lixeira_id"])
        assert missao is not None and missao.excluida_em is None
        assert missao.titulo == "Missao secreta do vizinho"
        assert tarefa is not None and tarefa.titulo == "Tarefa secreta"
        assert tarefa_lixo is not None and tarefa_lixo.excluida_em is not None
        assert missao_lixo is not None and missao_lixo.excluida_em is not None
        assert db.get(Coluna, cla_vizinho["coluna_id"]) is not None
        evento = db.get(Evento, cla_vizinho["evento_id"])
        assert evento is not None and evento.titulo == "Workshop do vizinho"
        assert evento.excluido_em is None
        assert db.get(Evento, cla_vizinho["evento_lixeira_id"]).excluido_em is not None
        # A tentativa de concluir a missao do vizinho nao pode ter criado entrega em cla nenhum.
        assert db.scalar(select(func.count(Entrega.id)).where(Entrega.cla_id == cla_id)) == 0
        assert (
            db.scalar(
                select(func.count(Entrega.id)).where(Entrega.missao_id == cla_vizinho["missao_id"])
            )
            == 0
        )
