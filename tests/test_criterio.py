"""Um criterio so para "isso vale ponto", conferido pelos cinco lugares que o leem.

O dashboard tem cinco leitores da mesma verdade: os numeros do cla (agregacao em SQL), o ranking,
o relatorio que abre na linha da pessoa, o grafico de barras e a barra de progresso do cartao. Mais
o ponto do quadro em /minhas. Eles liam a mesma tabela por caminhos diferentes, e tres deles nao
checavam coluna_id.

Com o cartao numa coluna privada e marcado concluido pelo formulario da missao, a tela mostrava
100 pontos gerados e todo mundo com 0 no ranking, ao mesmo tempo. Nao existia teste que somasse as
partes e conferisse com o total, entao a divergencia nao tinha como aparecer.

Aqui a conta tem que FECHAR: a soma do ranking bate com os pontos gerados, e a soma do grafico bate
com as entregas concluidas. Banco proprio, pelo mesmo motivo dos outros modulos de teste.
"""

from __future__ import annotations

import pytest

from app.models import A_FAZER, CONCLUIDO, FAZENDO, Coluna, Entrega, Missao, agora
from app.repositorios import entregas as repo_entregas
from app.repositorios import missoes as repo_missoes
from app.servicos.missoes import conta_como_concluida
from app.servicos.quadro import montar_itens, pontos
from app.servicos.ranking import (
    numeros_do_cla,
    progresso_da_missao,
    quem_fez_cada_missao,
    ranking,
)
from tests import fabrica

# Populacao montada na mao para cobrir as quatro combinacoes de status x coluna, mais uma conclusao
# em missao que esta na lixeira. Esperado: 150 pontos e 2 entregas, so de Ana.
PONTOS_ESPERADOS = 150
CONCLUIDAS_ESPERADAS = 2


@pytest.fixture(scope="module")
def cenario():
    with fabrica.banco("criterio") as (Sessao, _engine):
        with Sessao() as db:
            cla = fabrica.criar_cla(db, "Cla do Criterio")
            ana = fabrica.entrar(db, cla, "Ana", "a@c.com")
            bruno = fabrica.entrar(db, cla, "Bruno", "b@c.com")
            clara = fabrica.entrar(db, cla, "Clara", "c@c.com")

            def entrega(**campos) -> Entrega:
                return Entrega(cla_id=cla.id, **campos)

            gaveta_bruno = Coluna(
                cla_id=cla.id, membro_id=bruno.id, nome="Gaveta do Bruno", ordem=1
            )
            missao = dict(cla_id=cla.id, descricao="", criada_por_id=ana.id)
            m1 = Missao(titulo="M1", pontos=100, **missao)
            m2 = Missao(titulo="M2", pontos=50, **missao)
            m3 = Missao(titulo="M3 na lixeira", pontos=70, **missao)
            db.add_all([gaveta_bruno, m1, m2, m3])
            db.flush()
            m3.excluida_em = agora()

            db.add_all(
                [
                    # conta: concluida e fora de coluna privada
                    entrega(missao_id=m1.id, membro_id=ana.id, status=CONCLUIDO),
                    entrega(missao_id=m2.id, membro_id=ana.id, status=CONCLUIDO),
                    # nao conta: concluida, mas guardada numa coluna que so o Bruno ve
                    entrega(
                        missao_id=m1.id,
                        membro_id=bruno.id,
                        status=CONCLUIDO,
                        coluna_id=gaveta_bruno.id,
                    ),
                    # nao conta: nem chegou em concluida
                    entrega(missao_id=m1.id, membro_id=clara.id, status=FAZENDO),
                    entrega(missao_id=m2.id, membro_id=bruno.id, status=A_FAZER),
                    # nao conta: concluida, mas a missao esta na lixeira
                    entrega(missao_id=m3.id, membro_id=ana.id, status=CONCLUIDO),
                ]
            )
            db.commit()

            escopo_ana = fabrica.escopo(db, ana)
            yield {
                "ana": escopo_ana,
                "bruno": fabrica.escopo(db, bruno),
                "gaveta": gaveta_bruno,
                "missoes": repo_missoes.ativas(escopo_ana, com_entregas=True),
            }


def test_sql_e_python_concordam_sobre_o_que_conta(cenario):
    """O criterio existe duas vezes, em SQL e em Python. Aqui as duas versoes se encaram."""
    missoes = cenario["missoes"]
    por_sql = repo_entregas.pontuacao_concluida(cenario["ana"])
    por_python = (
        sum(m.pontos for m in missoes for e in m.entregas if conta_como_concluida(e)),
        sum(1 for m in missoes for e in m.entregas if conta_como_concluida(e)),
    )
    assert por_sql == por_python == (PONTOS_ESPERADOS, CONCLUIDAS_ESPERADAS)


def test_soma_do_ranking_fecha_com_os_pontos_gerados(cenario):
    numeros = numeros_do_cla(cenario["ana"], cenario["missoes"])
    soma = sum(linha["pontos"] for linha in ranking(cenario["ana"], cenario["missoes"]))
    assert soma == numeros["pontos_gerados"] == PONTOS_ESPERADOS


def test_soma_do_grafico_fecha_com_as_entregas_concluidas(cenario):
    numeros = numeros_do_cla(cenario["ana"], cenario["missoes"])
    barras = quem_fez_cada_missao(cenario["ana"], cenario["missoes"])
    soma = sum(barra["quantidade"] for barra in barras)
    assert soma == numeros["entregas_concluidas"] == CONCLUIDAS_ESPERADAS


def test_barra_de_progresso_nao_conta_cartao_em_gaveta(cenario):
    """M1 tem duas entregas concluidas na tabela, mas uma esta em coluna privada."""
    m1 = [m for m in cenario["missoes"] if m.titulo == "M1"][0]
    assert len([e for e in m1.entregas if e.status == CONCLUIDO]) == 2
    assert progresso_da_missao(m1, 3)["feitas"] == 1


def test_grafico_nao_nomeia_quem_esta_com_o_cartao_na_gaveta(cenario):
    barras = quem_fez_cada_missao(cenario["ana"], cenario["missoes"])
    barra = [b for b in barras if b["missao"].titulo == "M1"][0]
    assert [q["nome"] for q in barra["quem"]] == ["Ana"]


def test_quadro_do_bruno_concorda_com_o_ranking_dele(cenario):
    """O Bruno ve o proprio cartao na gaveta; nem ali nem no ranking ele tem ponto."""
    bruno = cenario["bruno"]
    itens = montar_itens(bruno, {cenario["gaveta"].id}, cenario["missoes"])
    linhas = ranking(bruno, cenario["missoes"])
    linha = [linha for linha in linhas if linha["membro"].id == bruno.membro_id][0]
    assert pontos(itens) == linha["pontos"] == 0
