"""Trava o numero de consultas do dashboard.

Consulta escondida nao aparece lendo codigo nem cronometrando com pouco dado: com uma missao no
banco, a versao que ia ao banco uma vez por missao parecia tao rapida quanto a que vai uma vez so.
So aparece contando, e com dado suficiente para a curva crescer.

Antes da separacao em repositorios, este mesmo dashboard disparava 12 consultas com 1 missao e 70
com 30: duas a mais por missao adicionada. Se alguem reintroduzir um lazy-load dentro de um laco,
e aqui que estoura, e nao em producao seis meses depois.

O banco daqui e proprio, criado e apagado no escopo deste modulo. Ele nao pode usar o banco das
outras suites: varias assercoes de test_fluxo contam linhas do ranking e do grafico, e inflar o
numero de missoes quebraria aquelas contagens.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.database import Base
from app.models import CONCLUIDO, A_FAZER, Entrega, Missao
from app.repositorios import missoes as repo_missoes
from app.servicos.calendario import eventos_do_cla
from app.servicos.ranking import (
    numeros_do_cla,
    progresso_da_missao,
    quem_fez_cada_missao,
    ranking,
)
from tests import fabrica

TOTAL_MEMBROS = 9


@pytest.fixture(scope="module")
def banco():
    with fabrica.banco("consultas") as (Sessao, engine):
        yield Sessao, engine


def _povoar(db, quantas_missoes: int):
    """Um cla com nove pessoas e N missoes, metade das entregas concluida. Devolve o escopo.

    O segundo cla que aparece a partir daqui e do teste de isolamento, nao deste: aqui o que
    interessa e a curva de consultas por missao, e ela nao muda com mais cla no banco.
    """
    cla = fabrica.criar_cla(db, "Cla da Contagem")
    membros = [fabrica.entrar(db, cla, f"Pessoa{i}") for i in range(TOTAL_MEMBROS)]
    for n in range(quantas_missoes):
        missao = Missao(
            cla_id=cla.id,
            titulo=f"Missao {n}",
            descricao="",
            pontos=100,
            criada_por_id=membros[0].id,
        )
        db.add(missao)
        db.flush()
        for indice, membro in enumerate(membros):
            db.add(
                Entrega(
                    cla_id=cla.id,
                    missao_id=missao.id,
                    membro_id=membro.id,
                    status=CONCLUIDO if indice % 2 == 0 else A_FAZER,
                )
            )
    db.commit()


def _consultas_do_dashboard(Sessao, engine, quantas_missoes: int) -> int:
    """Roda o mesmo trabalho da rota GET / e devolve quantos SELECT sairam."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Sessao() as db:
        _povoar(db, quantas_missoes)

    disparadas: list[str] = []

    def anotar(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        disparadas.append(statement)

    with Sessao() as db:
        # Fora da contagem de proposito: e o que a rota ja tem resolvido pela sessao do login.
        escopo = fabrica.escopo(db, fabrica.qualquer_membro(db))
        event.listen(engine, "before_cursor_execute", anotar)
        try:
            missoes = repo_missoes.ativas(escopo, com_entregas=True)
            numeros = numeros_do_cla(escopo, missoes)
            for missao in missoes:
                progresso_da_missao(missao, numeros["total_membros"])
            ranking(escopo, missoes)
            quem_fez_cada_missao(escopo, missoes)
            eventos_do_cla(escopo, missoes, escopo.membro_id)
        finally:
            event.remove(engine, "before_cursor_execute", anotar)
    return len(disparadas)


def test_dashboard_nao_consulta_mais_por_ter_mais_missao(banco):
    Sessao, engine = banco
    com_poucas = _consultas_do_dashboard(Sessao, engine, 3)
    com_muitas = _consultas_do_dashboard(Sessao, engine, 30)
    assert com_poucas == com_muitas, (
        f"o dashboard passou de {com_poucas} para {com_muitas} consultas so por ter mais missao: "
        "alguem percorreu missao.entregas sem carregar junto"
    )


def test_dashboard_cabe_num_punhado_de_consultas(banco):
    """Teto folgado de proposito: o que importa e nao voltar para a casa das dezenas."""
    Sessao, engine = banco
    assert _consultas_do_dashboard(Sessao, engine, 30) <= 12
