"""A regra do quadro exercitada sem servidor no ar.

Este arquivo e a razao pratica de `app/routers/pessoal.py` ter sido quebrado. Enquanto
`_resolver_destino`, `_colocar` e `_quadro` moravam dentro do router, a unica forma de chegar
neles era por HTTP: subir app, criar conta, fazer login, postar formulario. Cada caso de borda
custava um fluxo inteiro, entao os casos de borda simplesmente nao eram testados.

Banco proprio, criado e apagado no escopo do modulo, pelo mesmo motivo de test_consultas.py: as
assercoes de test_fluxo contam linhas do ranking e do grafico, e membro ou missao a mais quebraria
aquelas contagens.
"""

from __future__ import annotations

import pytest

from app.models import A_FAZER, CONCLUIDO, FAZENDO, Coluna, Missao, TarefaPessoal
from app.repositorios import entregas as repo_entregas
from app.servicos.erros import DestinoInvalido, NaoEncontrado
from app.servicos.quadro import colocar, montar_itens, montar_quadro, pontos, resolver_destino
from app.servicos.tarefas import data_ou_nada, minha_tarefa
from tests import fabrica


@pytest.fixture(scope="module")
def cenario():
    """Ana e Bruno, uma coluna de cada, uma missao de 100 pontos e uma tarefa da Ana.

    O que o teste recebe e o escopo de cada uma, nao a sessao: as funcoes de servico deixaram de
    aceitar `db` e `membro` soltos. Passar a sessao de um pedido com o membro de outro era
    possivel, e o escopo e o que fechou essa porta.
    """
    with fabrica.banco("quadro") as (Sessao, _engine):
        with Sessao() as db:
            cla = fabrica.criar_cla(db, "Cla do Teste")
            ana = fabrica.entrar(db, cla, "Ana", "ana@q.com")
            bruno = fabrica.entrar(db, cla, "Bruno", "bruno@q.com")
            col_ana = Coluna(cla_id=cla.id, membro_id=ana.id, nome="Gaveta da Ana", ordem=1)
            col_bruno = Coluna(cla_id=cla.id, membro_id=bruno.id, nome="Gaveta do Bruno", ordem=1)
            missao = Missao(
                cla_id=cla.id, titulo="Resumo", descricao="", pontos=100, criada_por_id=ana.id
            )
            tarefa = TarefaPessoal(
                cla_id=cla.id, membro_id=ana.id, titulo="So minha", status=A_FAZER
            )
            db.add_all([col_ana, col_bruno, missao, tarefa])
            db.commit()
            yield {
                "ana": fabrica.escopo(db, ana),
                "bruno": fabrica.escopo(db, bruno),
                "db": db,
                "col_ana": col_ana,
                "col_bruno": col_bruno,
                "missao": missao,
                "tarefa": tarefa,
            }


def test_destino_de_status_nao_usa_coluna(cenario):
    assert resolver_destino(cenario["ana"], FAZENDO) == (None, FAZENDO)


def test_coluna_propria_aceita_mas_nao_pontua(cenario):
    """Cartao em coluna privada volta para a_fazer: coluna que so o dono ve nao vale ponto."""
    coluna = cenario["col_ana"]
    assert resolver_destino(cenario["ana"], f"c{coluna.id}") == (coluna.id, A_FAZER)


def test_coluna_de_outro_membro_e_destino_invalido(cenario):
    with pytest.raises(DestinoInvalido):
        resolver_destino(cenario["ana"], f"c{cenario['col_bruno'].id}")


def test_coluna_que_nao_existe_da_o_mesmo_erro_da_coluna_alheia(cenario):
    """Mesmo erro de proposito: a resposta nao pode dizer se o id existe."""
    with pytest.raises(DestinoInvalido):
        resolver_destino(cenario["ana"], "c999999")


@pytest.mark.parametrize("lixo", ["", "cabc", "concluidoo", "c", "-1", "missao-1"])
def test_destino_torto_nunca_passa(cenario, lixo):
    with pytest.raises(DestinoInvalido):
        resolver_destino(cenario["ana"], lixo)


def test_tarefa_de_outro_membro_e_nao_encontrada(cenario):
    with pytest.raises(NaoEncontrado):
        minha_tarefa(cenario["bruno"], cenario["tarefa"].id)


def test_chave_torta_nao_move_nada_e_nao_estoura(cenario):
    assert colocar(cenario["ana"], "missao-abc", None, CONCLUIDO, 0) is None
    assert colocar(cenario["ana"], "lixo", None, CONCLUIDO, 0) is None


def test_arrastar_para_coluna_privada_derruba_o_status(cenario):
    """Arrastar nunca deixa concluido dentro de coluna privada: resolver_destino forca a_fazer."""
    ana = cenario["ana"]
    coluna_id, status = resolver_destino(ana, f"c{cenario['col_ana'].id}")
    colocar(ana, f"missao-{cenario['missao'].id}", coluna_id, status, 0)
    cenario["db"].commit()
    itens = montar_itens(ana, {cenario["col_ana"].id}, [cenario["missao"]])
    assert pontos(itens) == 0


def test_concluido_dentro_de_coluna_privada_nao_conta_ponto(cenario):
    """O ponto vem de ONDE o cartao esta, nao do status guardado.

    Este estado (status concluido com coluna_id preenchido) nao sai de arrastar: sai de arrastar
    para a coluna privada e depois marcar concluido pelo formulario da missao, que nunca limpa
    coluna_id. Escrevo a combinacao na mao porque e assim que ela aparece em producao.
    """
    ana = cenario["ana"]
    entrega = repo_entregas.obter_ou_criar(ana, cenario["missao"].id, ana.membro_id)
    entrega.coluna_id = cenario["col_ana"].id
    entrega.status = CONCLUIDO
    cenario["db"].commit()
    itens = montar_itens(ana, {cenario["col_ana"].id}, [cenario["missao"]])
    assert pontos(itens) == 0


def test_concluido_fora_de_coluna_pontua(cenario):
    ana = cenario["ana"]
    colocar(ana, f"missao-{cenario['missao'].id}", None, CONCLUIDO, 0)
    cenario["db"].commit()
    itens = montar_itens(ana, {cenario["col_ana"].id}, [cenario["missao"]])
    assert pontos(itens) == 100


def test_quadro_respeita_a_ordem_salva_e_joga_coluna_nova_no_fim(cenario):
    coluna = cenario["col_ana"]
    itens = montar_itens(cenario["ana"], {coluna.id}, [cenario["missao"]])
    chaves = [g["chave"] for g in montar_quadro(itens, [coluna], "concluido,a_fazer,fazendo")]
    assert chaves == ["concluido", "a_fazer", "fazendo", f"c{coluna.id}"]


def test_quadro_sem_ordem_salva_comeca_pelos_status_padrao(cenario):
    coluna = cenario["col_ana"]
    itens = montar_itens(cenario["ana"], {coluna.id}, [cenario["missao"]])
    chaves = [g["chave"] for g in montar_quadro(itens, [coluna], "")]
    assert chaves == ["a_fazer", "fazendo", "concluido", f"c{coluna.id}"]


def test_tarefa_do_outro_nao_entra_nos_itens(cenario):
    itens = montar_itens(cenario["bruno"], {cenario["col_bruno"].id}, [cenario["missao"]])
    assert f"pessoal-{cenario['tarefa'].id}" not in {i["chave"] for i in itens}


@pytest.mark.parametrize("texto", ["", "30/02/2026", "2026-02-30", "ontem", "2026-13-01"])
def test_data_impossivel_vira_sem_prazo(texto):
    assert data_ou_nada(texto) is None


def test_data_boa_e_lida(cenario):  # noqa: ARG001
    assert data_ou_nada(" 2026-09-25 ").isoformat() == "2026-09-25"
