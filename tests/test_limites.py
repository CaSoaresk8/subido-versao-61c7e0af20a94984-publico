"""Os tetos por IP: senha em massa, cadastro em massa e o video de 22 MB em laco.

Sao a resposta a uma pergunta concreta do Caio, depois de alguem na comunidade dizer que ia copiar
a plataforma: o que acontece se derem scrap no sistema. Copiar a aparencia ninguem impede. O que da
para impedir e o barato: testar senha aos milhares, encher a base de conta falsa e torrar banda.

O relogio entra por parametro nos testes de unidade, para a janela e o castigo serem exercitados
sem dormir de verdade.
"""

from __future__ import annotations

import pytest

from app.servicos import limites


@pytest.fixture
def limitador():
    # 3 tentativas em 60s, 120s de castigo. Numeros pequenos para o teste ler facil.
    return limites.Limitador((3, 60, 120), "teste")


def test_libera_ate_o_limite_e_bloqueia_no_ultimo(limitador):
    assert limitador.registrar("ip", agora=0) == 0
    assert limitador.registrar("ip", agora=1) == 0
    assert limitador.registrar("ip", agora=2) == 120, "a terceira tentativa tinha que bloquear"
    assert limitador.bloqueado("ip", agora=3) == 119


def test_o_bloqueio_acaba_sozinho(limitador):
    for instante in (0, 1, 2):
        limitador.registrar("ip", agora=instante)
    # O castigo comeca na terceira tentativa (instante 2), entao termina em 122.
    assert limitador.bloqueado("ip", agora=121) == 1
    assert limitador.bloqueado("ip", agora=123) == 0
    assert limitador.registrar("ip", agora=123) == 0, "depois do castigo, volta a contar do zero"


def test_janela_deslizante_nao_guarda_rancor(limitador):
    """Errar uma vez de manha nao pode deixar a pessoa mais perto do bloqueio a noite."""
    limitador.registrar("ip", agora=0)
    limitador.registrar("ip", agora=61)  # a primeira ja saiu da janela de 60s
    limitador.registrar("ip", agora=62)
    assert limitador.bloqueado("ip", agora=63) == 0


def test_cada_chave_conta_sozinha(limitador):
    for instante in (0, 1, 2):
        limitador.registrar("ip-a", agora=instante)
    assert limitador.bloqueado("ip-a", agora=3) > 0
    assert limitador.bloqueado("ip-b", agora=3) == 0, "bloqueou um IP inocente"


def test_limpar_esquece_a_chave(limitador):
    limitador.registrar("ip", agora=0)
    limitador.registrar("ip", agora=1)
    limitador.limpar("ip")
    assert limitador.registrar("ip", agora=2) == 0


# ----------------------------------------------------------------------------------------------
# Pelas rotas, que e onde isso vale
# ----------------------------------------------------------------------------------------------


def test_senha_errada_repetida_para_de_responder(visitante):
    alvo = {"email": "ana@cla.com", "senha": "errada"}
    respostas = [visitante.post("/login", data=alvo).status_code for _ in range(9)]
    assert respostas[0] == 401, "a primeira tentativa tem que ser um 401 normal"
    assert 429 in respostas, f"nenhuma tentativa foi barrada: {respostas}"
    barrada = visitante.post("/login", data=alvo)
    assert barrada.status_code == 429
    assert "Tentativas demais" in barrada.text


def test_a_senha_certa_limpa_o_castigo(app_web, ana):  # noqa: ARG001
    """Quem erra duas vezes e lembra na terceira nao pode sair marcado."""
    from fastapi.testclient import TestClient

    cliente = TestClient(app_web)
    for _ in range(3):
        cliente.post("/login", data={"email": "ana@cla.com", "senha": "errada"})
    entrada = cliente.post(
        "/login", data={"email": "ana@cla.com", "senha": "senhaforte1"}, follow_redirects=False
    )
    assert entrada.status_code == 303, entrada.text

    outro = TestClient(app_web)
    for _ in range(4):
        outro.post("/login", data={"email": "ana@cla.com", "senha": "errada"})
    assert outro.post("/login", data={"email": "ana@cla.com", "senha": "errada"}).status_code == 401


def _limpar_robos() -> None:
    """Apaga SO o que este teste cria (emails @spam.local), de dentro para fora pelas FKs.

    O banco e compartilhado com a suite inteira. Deixar dez clas de robo para tras mudaria as
    contagens que outros arquivos conferem, e o teste vermelho apareceria longe daqui.
    """
    from sqlalchemy import delete, select

    from app.database import SessionLocal
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

    db = SessionLocal()
    contas = list(db.scalars(select(Usuario.id).where(Usuario.email.like("%@spam.local"))))
    if contas:
        clas = list(
            db.scalars(select(Membro.cla_id).where(Membro.usuario_id.in_(contas)).distinct())
        )
        for modelo in (Log, Entrega, TarefaPessoal, Coluna, Convite, Missao, Membro):
            db.execute(delete(modelo).where(modelo.cla_id.in_(clas)))
        db.execute(delete(Cla).where(Cla.id.in_(clas)))
        db.execute(delete(Usuario).where(Usuario.id.in_(contas)))
        db.commit()
    db.close()


def test_cadastro_em_massa_e_barrado_nas_duas_portas(app_web, gerar_convite, ana):
    """Criar cla e entrar por convite dividem o MESMO contador: sao a mesma conta nova nascendo.

    Cliente PROPRIO, e nao a fixture `visitante`: criar cla LOGA quem criou, e usar o cliente
    compartilhado deixaria a suite inteira com um visitante que nao e mais visitante. Isso ja
    aconteceu aqui e quebrou dez testes de outros arquivos.
    """
    from fastapi.testclient import TestClient

    _limpar_robos()
    cliente = TestClient(app_web)
    _, token = gerar_convite(ana, dias=7, max_usos="")
    try:
        for i in range(limites.CADASTRO[0]):
            cliente.post(
                "/criar-cla",
                data={
                    "nome_cla": f"Cla robo {i}",
                    "nome": "Robo",
                    "email": f"robo{i}@spam.local",
                    "telefone": "11900000000",
                    "senha": "senhaforte1",
                },
            )
        barrado = cliente.post(
            "/criar-cla",
            data={
                "nome_cla": "Mais um",
                "nome": "Robo",
                "email": "robo-extra@spam.local",
                "telefone": "11900000000",
                "senha": "senhaforte1",
            },
        )
        assert barrado.status_code == 429
        assert "Muitos cadastros" in barrado.text

        # A outra porta, com o mesmo contador. A tela do convite recusado responde 400, que e o
        # mesmo codigo de convite vencido ou esgotado.
        pelo_convite = cliente.post(
            f"/convite/{token}",
            data={
                "nome": "Robo",
                "email": "robo-convite@spam.local",
                "telefone": "11900000000",
                "senha": "senhaforte1",
            },
        )
        assert pelo_convite.status_code == 400
        assert "Muitos cadastros" in pelo_convite.text
    finally:
        _limpar_robos()


def test_video_em_laco_e_barrado_e_o_resto_do_static_nao(visitante):
    codigos = [
        visitante.get("/static/tutorial.mp4", headers={"Range": "bytes=0-99"}).status_code
        for _ in range(limites.VIDEO[0] + 1)
    ]
    assert codigos[0] in (200, 206), f"o primeiro download tem que passar: {codigos[0]}"
    assert codigos[-1] == 429, f"o laco nao foi barrado: {codigos}"
    # O teto e do arquivo pesado, e nao do /static inteiro: barrar o css deixaria o app sem estilo.
    assert visitante.get("/static/style.css").status_code == 200
