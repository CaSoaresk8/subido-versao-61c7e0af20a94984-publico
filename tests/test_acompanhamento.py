"""O acompanhamento semanal: "Eu assumo essa semana", a conversa com cada pessoa e o perfil.

Cla proprio, com tres pessoas e email marcador, apagado na entrada e na saida.

O que importa provar, alem de "funciona":
  - semana ja assumida nao se toma por clique: quem esta passa a vez;
  - so o responsavel registra conversa, e nunca sobre si mesmo;
  - o cla ve o status e quem conversou, mas o TEXTO e o perfil so a pessoa e o responsavel.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

MARCA = "diario-teste.local"


def _limpar() -> None:
    from sqlalchemy import delete, select

    from app.database import SessionLocal
    from app.models import (
        Acompanhamento,
        Cla,
        Coluna,
        Convite,
        DiarioEntrada,
        Entrega,
        Evento,
        Log,
        Membro,
        Mentoria,
        Missao,
        PerfilMembro,
        ResponsavelSemana,
        TarefaPessoal,
        Usuario,
    )

    db = SessionLocal()
    contas = list(db.scalars(select(Usuario.id).where(Usuario.email.like(f"%@{MARCA}"))))
    clas = list(db.scalars(select(Membro.cla_id).where(Membro.usuario_id.in_(contas)).distinct()))
    for modelo in (
        DiarioEntrada,
        PerfilMembro,
        ResponsavelSemana,
        Mentoria,
        Acompanhamento,
        Log,
        Evento,
        Entrega,
        TarefaPessoal,
        Coluna,
        Convite,
        Missao,
        Membro,
    ):
        db.execute(delete(modelo).where(modelo.cla_id.in_(clas)))
    db.execute(delete(Cla).where(Cla.id.in_(clas)))
    db.execute(delete(Usuario).where(Usuario.id.in_(contas)))
    db.commit()
    db.close()


@pytest.fixture(scope="module")
def cla(app_web, gerar_convite):
    _limpar()
    ana = TestClient(app_web)
    r = ana.post(
        "/criar-cla",
        data={
            "nome_cla": "Cla do Diario",
            "nome": "Ana Diario",
            "email": f"ana@{MARCA}",
            "telefone": "11966660000",
            "senha": "senhaforte1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    _, token = gerar_convite(ana, dias=7, max_usos="")
    pessoas = {"ana": ana}
    for apelido, nome in (("bia", "Bia Diario"), ("caio", "Caio Diario")):
        cliente = TestClient(app_web)
        entrada = cliente.post(
            f"/convite/{token}",
            data={
                "nome": nome,
                "email": f"{apelido}@{MARCA}",
                "telefone": "11966660001",
                "senha": "senhaforte1",
            },
            follow_redirects=False,
        )
        assert entrada.status_code == 303, entrada.text
        pessoas[apelido] = cliente
    try:
        yield pessoas
    finally:
        _limpar()


def _id(nome: str) -> int:
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Membro

    with SessionLocal() as db:
        return db.scalar(select(Membro.id).where(Membro.nome == nome))


def test_semana_sem_ninguem_mostra_o_botao_e_quem_clica_assume(cla):
    tela = cla["bia"].get("/acompanhamento").text
    assert "Eu assumo essa semana" in tela
    cla["ana"].post("/acompanhamento/assumir")
    assert "Você é responsável esta semana" in cla["ana"].get("/acompanhamento").text
    tela_bia = cla["bia"].get("/acompanhamento").text
    assert "Ana Diario</strong> é responsável" in tela_bia
    assert "Eu assumo essa semana" not in tela_bia
    # E o painel avisa quem assumiu: o app nao manda lembrete por fora.
    assert "Você assumiu o acompanhamento desta semana" in cla["ana"].get("/").text
    # O cla fica sabendo quem assumiu.
    assert "assumiu o acompanhamento da semana" in cla["caio"].get("/historico").text


def test_semana_assumida_nao_se_toma_por_clique(cla):
    r = cla["bia"].post("/acompanhamento/assumir", follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert "Ana Diario</strong> é responsável" in cla["bia"].get("/acompanhamento").text


def test_so_o_responsavel_registra_e_nunca_sobre_si(cla):
    bia, ana = _id("Bia Diario"), _id("Ana Diario")
    r = cla["caio"].post(
        f"/acompanhamento/{bia}/conversa", data={"status": "em_dia"}, follow_redirects=False
    )
    assert "erro=" in r.headers["location"], "quem nao assumiu conseguiu registrar"
    r = cla["ana"].post(
        f"/acompanhamento/{ana}/conversa", data={"status": "em_dia"}, follow_redirects=False
    )
    assert "erro=" in r.headers["location"], "o responsavel registrou conversa consigo mesmo"


def test_conversa_aparece_no_cartao_e_o_texto_so_para_quem_pode(cla):
    bia = _id("Bia Diario")
    cla["ana"].post(
        f"/acompanhamento/{bia}/conversa",
        data={
            "status": "travado",
            "como_esta": "Travada no pixel x31",
            "combinados": "Refazer o evento de compra",
        },
    )
    # O cla inteiro ve o status e quem conversou.
    cartoes = cla["caio"].get("/acompanhamento").text
    assert "Bia Diario" in cartoes and "Discutido" in cartoes
    foco = cla["ana"].get(f"/acompanhamento/{bia}").text
    assert 'data-pipeline' in foco and '/static/pipeline.js' in foco
    assert "Travada no pixel x31" in foco
    restrito = cla["caio"].get(f"/acompanhamento/{bia}").text
    assert "Travada no pixel x31" not in restrito
    assert "Refazer o evento de compra" not in restrito
    # O texto: a propria pessoa e o responsavel veem; o resto do cla nao.
    assert "x31" in cla["bia"].get(f"/acompanhamento/{bia}").text
    assert "x31" in cla["ana"].get(f"/acompanhamento/{bia}").text
    alheio = cla["caio"].get(f"/acompanhamento/{bia}").text
    assert "x31" not in alheio and "Refazer o evento" not in alheio, "o texto vazou para o cla"
    assert "Travado" in alheio
    # E nao vai para o historico do cla.
    assert "x31" not in cla["caio"].get("/historico").text


def test_perfil_a_pessoa_e_o_responsavel_editam_o_resto_nao(cla):
    bia = _id("Bia Diario")
    cla["bia"].post(
        f"/acompanhamento/{bia}/perfil",
        data={
            "sobre": "Gestora iniciante",
            "metas": "Fechar 3 clientes ate dezembro m77",
            "dificuldades": "Pixel",
        },
    )
    assert "m77" in cla["ana"].get(f"/acompanhamento/{bia}").text
    assert "m77" not in cla["caio"].get(f"/acompanhamento/{bia}").text
    assert (
        cla["caio"].post(f"/acompanhamento/{bia}/perfil", data={"metas": "invadido"}).status_code
        == 404
    )


def test_transferir_passa_a_semana_e_so_quem_esta_transfere(cla):
    caio = _id("Caio Diario")
    r = cla["bia"].post("/acompanhamento/transferir", data={"para": caio}, follow_redirects=False)
    assert "erro=" in r.headers["location"], "quem nao e responsavel transferiu"
    cla["ana"].post("/acompanhamento/transferir", data={"para": caio})
    assert "Você é responsável esta semana" in cla["caio"].get("/acompanhamento").text
    assert "Caio Diario</strong> é responsável" in cla["ana"].get("/acompanhamento").text
    assert "passou o acompanhamento da semana" in cla["bia"].get("/historico").text


def test_dois_botoes_sem_seletor_de_status(cla):
    bia = _id("Bia Diario")
    pagina = cla["caio"].get(f"/acompanhamento/{bia}").text
    assert 'type="radio" name="status"' not in pagina
    assert 'value="conversou">Registrar conversa' in pagina
    assert 'value="sem_resposta">Não respondeu' in pagina
    resposta = cla["caio"].post(
        f"/acompanhamento/{bia}/conversa",
        data={"status": "sem_resposta"},
    )
    assert resposta.status_code == 200
    assert "Não respondeu" in resposta.text
    resposta = cla["caio"].post(
        f"/acompanhamento/{bia}/conversa",
        data={"status": "conversou", "como_esta": "Feedback de validacao local", "combinados": "Tarefa de validacao local"},
    )
    assert resposta.status_code == 200
    assert "Feedback de validacao local" in resposta.text
    assert "Conversa registrada" in resposta.text
