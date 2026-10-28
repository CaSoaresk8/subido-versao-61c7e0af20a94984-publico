"""O rastreador: o papel da mentoria que acompanha pessoas atravessando os clas.

E o primeiro papel do app que ve alem do proprio cla, entao os testes aqui olham principalmente
para os limites disso:

  - so o dono da plataforma fabrica rastreador (o convite e a tela dele respondem 404 para o resto);
  - o rastreador ve APENAS os clas que ele escolheu, e id de fora da lista da o mesmo 404 de id que
    nao existe;
  - entrar num cla nao e silencioso: vira linha no historico DAQUELE cla, com o nome dele;
  - tarefa pessoal continua privada, inclusive para quem acompanha.

O cla deste arquivo e proprio, com email marcador, apagado na entrada e na saida: o banco e
compartilhado com a suite e contagem de outro arquivo nao pode mudar por causa daqui.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

MARCA = "rastreio-teste.local"
DONO = f"dono@{MARCA}"
PESSOA = f"pessoa@{MARCA}"
OUTRA = f"outra@{MARCA}"
RASTREADOR = f"rastreador@{MARCA}"
CLA_A = "Cla Acompanhado"
CLA_B = "Cla Nao Acompanhado"


def _limpar() -> None:
    from sqlalchemy import delete, select

    from app.database import SessionLocal
    from app.models import (
        Acompanhamento,
        Cla,
        Coluna,
        Convite,
        ConviteRastreador,
        Entrega,
        Evento,
        Log,
        Membro,
        Mentoria,
        Missao,
        Rastreador,
        RastreadorCla,
        TarefaPessoal,
        Usuario,
    )

    db = SessionLocal()
    contas = list(db.scalars(select(Usuario.id).where(Usuario.email.like(f"%@{MARCA}"))))
    if contas:
        rastreadores = list(
            db.scalars(select(Rastreador.id).where(Rastreador.usuario_id.in_(contas)))
        )
        clas = list(
            db.scalars(select(Membro.cla_id).where(Membro.usuario_id.in_(contas)).distinct())
        )
        db.execute(delete(Mentoria).where(Mentoria.cla_id.in_(clas)))
        db.execute(delete(Acompanhamento).where(Acompanhamento.cla_id.in_(clas)))
        db.execute(delete(RastreadorCla).where(RastreadorCla.rastreador_id.in_(rastreadores)))
        db.execute(delete(Rastreador).where(Rastreador.id.in_(rastreadores)))
        db.execute(
            delete(ConviteRastreador).where(ConviteRastreador.criado_por_usuario_id.in_(contas))
        )
        for modelo in (Log, Evento, Entrega, TarefaPessoal, Coluna, Convite, Missao, Membro):
            db.execute(delete(modelo).where(modelo.cla_id.in_(clas)))
        db.execute(delete(Cla).where(Cla.id.in_(clas)))
        db.execute(delete(Usuario).where(Usuario.id.in_(contas)))
        db.commit()
    db.close()


def _criar_cla(app_web, nome: str, quem: str, email: str) -> TestClient:
    cliente = TestClient(app_web)
    resposta = cliente.post(
        "/criar-cla",
        data={
            "nome_cla": nome,
            "nome": quem,
            "email": email,
            "telefone": "11955550000",
            "senha": "senhaforte1",
        },
        follow_redirects=False,
    )
    assert resposta.status_code == 303, resposta.text
    return cliente


@pytest.fixture(scope="module")
def mundo(app_web):
    """Dois clas: um que o rastreador vai acompanhar e outro que ele nao acompanha."""
    _limpar()
    dono = _criar_cla(app_web, CLA_A, "Dono Teste", DONO)
    pessoa = TestClient(app_web)
    from tests.conftest import _gerar_convite

    _, token = _gerar_convite(dono, dias=7, max_usos="")
    entrada = pessoa.post(
        f"/convite/{token}",
        data={
            "nome": "Pessoa Teste",
            "email": PESSOA,
            "telefone": "11955550001",
            "senha": "senhaforte1",
        },
        follow_redirects=False,
    )
    assert entrada.status_code == 303, entrada.text
    outro = _criar_cla(app_web, CLA_B, "Outra Teste", OUTRA)
    try:
        yield {"dono": dono, "pessoa": pessoa, "outro": outro, "app": app_web}
    finally:
        _limpar()


@pytest.fixture
def sou_dono(monkeypatch):
    """O dono da plataforma e quem pode fabricar rastreador. Nos testes, o DONO deste arquivo."""
    monkeypatch.setattr("app.servicos.agenda.DONOS_DA_PLATAFORMA", frozenset({DONO}))


def _gerar_convite_de_rastreador(dono: TestClient) -> str:
    import re

    criacao = dono.post(
        "/plataforma/rastreadores/convites",
        data={"dias": "7", "max_usos": "1"},
        follow_redirects=True,
    )
    assert criacao.status_code == 200, criacao.text
    achado = re.findall(r"/rastreador/convite/([\w-]+)", criacao.text)
    assert achado, "a tela nao mostrou o link do convite gerado"
    return achado[0]


def _virar_rastreador(app_web, token: str, email: str = RASTREADOR) -> TestClient:
    cliente = TestClient(app_web)
    resposta = cliente.post(
        f"/rastreador/convite/{token}",
        data={
            "nome": "Rastreador Teste",
            "email": email,
            "telefone": "11955550002",
            "senha": "senhaforte1",
        },
        follow_redirects=False,
    )
    assert resposta.status_code == 303, resposta.text
    assert resposta.headers["location"] == "/rastreador/clas"
    return cliente


def _id_da_pessoa(nome: str = "Pessoa Teste") -> int:
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Membro

    with SessionLocal() as db:
        return db.scalar(select(Membro.id).where(Membro.nome == nome))


# ---------------------------------------------------------------------------------------------
# Quem pode criar rastreador
# ---------------------------------------------------------------------------------------------


def test_so_o_dono_da_plataforma_ve_e_gera_convite(mundo, sou_dono):
    assert mundo["dono"].get("/plataforma/rastreadores").status_code == 200
    # Para quem nao e dono a tela nao existe, e nao "existe e nao e sua".
    assert mundo["pessoa"].get("/plataforma/rastreadores").status_code == 404
    assert (
        mundo["pessoa"]
        .post("/plataforma/rastreadores/convites", data={"dias": "7", "max_usos": "1"})
        .status_code
        == 404
    )


def test_convite_gasto_nao_vale_de_novo(mundo, sou_dono):
    token = _gerar_convite_de_rastreador(mundo["dono"])
    _virar_rastreador(mundo["app"], token)

    segundo = TestClient(mundo["app"])
    recusado = segundo.post(
        f"/rastreador/convite/{token}",
        data={
            "nome": "Penetra",
            "email": f"penetra@{MARCA}",
            "telefone": "11955550003",
            "senha": "senhaforte1",
        },
    )
    assert recusado.status_code == 400
    assert "inválido" in recusado.text or "vencido" in recusado.text


def test_convite_revogado_para_de_valer(mundo, sou_dono):
    import re

    token = _gerar_convite_de_rastreador(mundo["dono"])
    pagina = mundo["dono"].get("/plataforma/rastreadores").text
    convite_id = re.findall(r"/plataforma/rastreadores/convites/(\d+)/revogar", pagina)[0]
    mundo["dono"].post(f"/plataforma/rastreadores/convites/{convite_id}/revogar")
    assert TestClient(mundo["app"]).get(f"/rastreador/convite/{token}").status_code == 400


# ---------------------------------------------------------------------------------------------
# O que o rastreador ve, e o que ele nao ve
# ---------------------------------------------------------------------------------------------


def test_o_painel_so_mostra_os_clas_escolhidos(mundo, sou_dono):
    token = _gerar_convite_de_rastreador(mundo["dono"])
    rastreador = _virar_rastreador(mundo["app"], token, email=f"r2@{MARCA}")

    # Sem escolher nada, o painel esta vazio: acompanhar e uma escolha, nao um automatico.
    painel = rastreador.get("/rastreador")
    assert painel.status_code == 200
    assert "ainda não escolheu nenhum clã" in painel.text
    assert "Pessoa Teste" not in painel.text

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Cla

    with SessionLocal() as db:
        cla_a = db.scalar(select(Cla.id).where(Cla.nome == CLA_A))
        cla_b = db.scalar(select(Cla.id).where(Cla.nome == CLA_B))

    rastreador.post(f"/rastreador/clas/{cla_a}/acompanhar")
    painel = rastreador.get("/rastreador").text
    assert "Pessoa Teste" in painel and "Dono Teste" in painel
    assert "Outra Teste" not in painel, "apareceu gente de um cla que ele nao acompanha"

    # A ficha de alguem do cla nao acompanhado da 404, igual a id inexistente.
    assert rastreador.get(f"/rastreador/pessoa/{_id_da_pessoa('Outra Teste')}").status_code == 404
    assert rastreador.get("/rastreador/pessoa/99999").status_code == 404
    assert rastreador.get(f"/rastreador/pessoa/{_id_da_pessoa()}").status_code == 200

    # Parar de acompanhar devolve o painel ao estado anterior.
    rastreador.post(f"/rastreador/clas/{cla_b}/acompanhar")
    assert "Outra Teste" in rastreador.get("/rastreador").text
    rastreador.post(f"/rastreador/clas/{cla_b}/parar")
    assert "Outra Teste" not in rastreador.get("/rastreador").text


def test_o_cla_fica_sabendo_que_passou_a_ser_acompanhado(mundo, sou_dono):
    """Transparencia foi decisao do Caio: ninguem e acompanhado sem saber, e com o nome de quem."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Cla

    token = _gerar_convite_de_rastreador(mundo["dono"])
    rastreador = _virar_rastreador(mundo["app"], token, email=f"r3@{MARCA}")
    with SessionLocal() as db:
        cla_a = db.scalar(select(Cla.id).where(Cla.nome == CLA_A))

    rastreador.post(f"/rastreador/clas/{cla_a}/acompanhar")
    historico = mundo["pessoa"].get("/historico").text
    assert "Rastreador Teste" in historico
    assert "passou a acompanhar" in historico

    rastreador.post(f"/rastreador/clas/{cla_a}/parar")
    assert "parou de acompanhar" in mundo["pessoa"].get("/historico").text


def test_tarefa_pessoal_nao_aparece_para_quem_acompanha(mundo, sou_dono):
    """O combinado com a mentoria ele ve; o que a pessoa anota para ela mesma, nao."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Cla

    mundo["pessoa"].post("/minhas/tarefas", data={"titulo": "Anotacao privada zzz9", "prazo": ""})
    token = _gerar_convite_de_rastreador(mundo["dono"])
    rastreador = _virar_rastreador(mundo["app"], token, email=f"r4@{MARCA}")
    with SessionLocal() as db:
        cla_a = db.scalar(select(Cla.id).where(Cla.nome == CLA_A))
    rastreador.post(f"/rastreador/clas/{cla_a}/acompanhar")

    ficha = rastreador.get(f"/rastreador/pessoa/{_id_da_pessoa()}")
    assert ficha.status_code == 200
    assert "zzz9" not in ficha.text, "a tarefa privada da pessoa apareceu para quem acompanha"
    assert "Nenhuma tarefa combinada com a mentoria" in ficha.text


def test_rastreador_sem_cla_entra_pelo_login(mundo, sou_dono):
    """Ele pode nao participar de cla nenhum: sem isto cairia na tela de "crie um cla"."""
    token = _gerar_convite_de_rastreador(mundo["dono"])
    _virar_rastreador(mundo["app"], token, email=f"r5@{MARCA}")

    novo = TestClient(mundo["app"])
    entrada = novo.post(
        "/login", data={"email": f"r5@{MARCA}", "senha": "senhaforte1"}, follow_redirects=False
    )
    assert entrada.status_code == 303
    assert entrada.headers["location"] == "/rastreador"
    assert novo.get("/rastreador").status_code == 200


def test_quem_nao_e_rastreador_nao_abre_o_painel(mundo):
    assert mundo["pessoa"].get("/rastreador", follow_redirects=False).status_code == 303
    assert TestClient(mundo["app"]).get("/rastreador", follow_redirects=False).status_code == 303


# ---------------------------------------------------------------------------------------------
# Etapas B e C: o que o rastreador FAZ na ficha da pessoa
# ---------------------------------------------------------------------------------------------

import itertools  # noqa: E402

_numero = itertools.count(100)


@pytest.fixture
def acompanhando(mundo, sou_dono):
    """Um rastreador novo, ja acompanhando o cla A. Novo a cada teste, para um nao herdar o outro."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Cla

    token = _gerar_convite_de_rastreador(mundo["dono"])
    rastreador = _virar_rastreador(mundo["app"], token, email=f"r{next(_numero)}@{MARCA}")
    with SessionLocal() as db:
        cla_a = db.scalar(select(Cla.id).where(Cla.nome == CLA_A))
    rastreador.post(f"/rastreador/clas/{cla_a}/acompanhar")
    return rastreador


def _ficha(rastreador) -> str:
    return rastreador.get(f"/rastreador/pessoa/{_id_da_pessoa()}").text


def test_tarefa_da_mentoria_aparece_para_a_pessoa_com_o_nome_de_quem_criou(mundo, acompanhando):
    pessoa_id = _id_da_pessoa()
    acompanhando.post(
        f"/rastreador/pessoa/{pessoa_id}/tarefas",
        data={"titulo": "Revisar criativos da semana", "descricao": "", "prazo": "2026-10-01"},
    )
    assert "Revisar criativos da semana" in _ficha(acompanhando)
    quadro = mundo["pessoa"].get("/minhas").text
    assert "Revisar criativos da semana" in quadro
    assert "mentoria" in quadro and "Rastreador Teste" in quadro, "o cartao nao diz de onde veio"


def test_rastreador_muda_status_da_tarefa_e_nao_toca_na_pessoal(mundo, acompanhando):
    import re

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import TarefaPessoal

    pessoa_id = _id_da_pessoa()
    acompanhando.post(
        f"/rastreador/pessoa/{pessoa_id}/tarefas", data={"titulo": "Tarefa para concluir x7"}
    )
    ficha = _ficha(acompanhando)
    tarefa_id = re.findall(rf"/rastreador/pessoa/{pessoa_id}/tarefas/(\d+)", ficha)[-1]
    acompanhando.post(
        f"/rastreador/pessoa/{pessoa_id}/tarefas/{tarefa_id}",
        data={"titulo": "Tarefa para concluir x7", "status": "concluido"},
    )
    with SessionLocal() as db:
        assert db.get(TarefaPessoal, int(tarefa_id)).status == "concluido"
    # Tarefa que a propria pessoa criou: para o rastreador, ela nao existe.
    mundo["pessoa"].post("/minhas/tarefas", data={"titulo": "So minha", "prazo": ""})
    with SessionLocal() as db:
        pessoal = db.scalar(
            select(TarefaPessoal.id).where(
                TarefaPessoal.membro_id == pessoa_id,
                TarefaPessoal.criada_por_rastreador_id.is_(None),
            )
        )
    resposta = acompanhando.post(
        f"/rastreador/pessoa/{pessoa_id}/tarefas/{pessoal}",
        data={"titulo": "invadida", "status": "concluido"},
    )
    assert resposta.status_code == 404


def test_entrega_pelo_rastreador_respeita_a_regra_da_resposta_e_aparece_no_historico(
    mundo, acompanhando
):
    import re

    criacao = mundo["dono"].post(
        "/missoes/nova",
        data={
            "titulo": "Missao com resumo r9",
            "pontos": "100",
            "exige_resposta": "1",
            "rotulo_resposta": "Link do resumo",
        },
        follow_redirects=False,
    )
    missao_id = re.findall(r"/missoes/(\d+)", criacao.headers["location"])[0]
    pessoa_id = _id_da_pessoa()

    sem_resposta = acompanhando.post(
        f"/rastreador/pessoa/{pessoa_id}/missoes/{missao_id}",
        data={"status": "concluido", "resposta": ""},
        follow_redirects=False,
    )
    assert "erro=" in sem_resposta.headers["location"], "concluiu sem a resposta exigida"

    acompanhando.post(
        f"/rastreador/pessoa/{pessoa_id}/missoes/{missao_id}",
        data={"status": "concluido", "resposta": "https://docs.exemplo/resumo"},
    )
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Entrega

    with SessionLocal() as db:
        entrega = db.scalar(
            select(Entrega).where(
                Entrega.missao_id == int(missao_id), Entrega.membro_id == pessoa_id
            )
        )
    assert entrega.status == "concluido" and entrega.resposta == "https://docs.exemplo/resumo"
    historico = mundo["pessoa"].get("/historico").text
    assert "Rastreador Teste (mentoria) marcou Pessoa Teste como Concluído" in historico


def test_saldo_de_consultorias_consome_devolve_e_trava(mundo, acompanhando):
    import re

    pessoa_id = _id_da_pessoa()
    base = f"/rastreador/pessoa/{pessoa_id}"
    # Um saldo pequeno para o teste chegar no limite: 2 mensais e 1 livre.
    acompanhando.post(f"{base}/saldo", data={"mensais": "2", "livres": "1"})

    for dia in ("2026-10-05T20:00", "2026-11-05T20:00"):
        acompanhando.post(f"{base}/mentorias", data={"tipo": "mensal", "inicio": dia})
    ficha = _ficha(acompanhando)
    assert "0</span>" in ficha  # nenhuma mensal restando

    # Sem saldo, a terceira e recusada com a frase certa.
    recusa = acompanhando.post(
        f"{base}/mentorias",
        data={"tipo": "mensal", "inicio": "2026-12-05T20:00"},
        follow_redirects=False,
    )
    assert "erro=" in recusa.headers["location"]

    # Cancelar devolve o saldo; faltou continua gastando.
    ids = re.findall(rf"{base}/mentorias/(\d+)", _ficha(acompanhando))
    acompanhando.post(f"{base}/mentorias/{ids[0]}", data={"situacao": "cancelada"})
    acompanhando.post(f"{base}/mentorias/{ids[1]}", data={"situacao": "faltou"})
    from app.database import SessionLocal
    from app.models import Membro
    from app.servicos.mentoria import saldo

    with SessionLocal() as db:
        s = saldo(db, db.get(Membro, pessoa_id))
    assert s["mensal"] == {"total": 2, "usadas": 1, "restam": 1}

    # Nao da para baixar o total para menos do que ja foi usado.
    abaixo = acompanhando.post(
        f"{base}/saldo", data={"mensais": "0", "livres": "1"}, follow_redirects=False
    )
    assert "erro=" in abaixo.headers["location"]


def test_a_pessoa_ve_o_saldo_mas_nao_a_anotacao_do_rastreador(mundo, acompanhando):
    pessoa_id = _id_da_pessoa()
    base = f"/rastreador/pessoa/{pessoa_id}"
    acompanhando.post(f"{base}/anotacao", data={"anotacao": "Travada no pixel, anotacao q1"})
    acompanhando.post(f"{base}/mentorias", data={"tipo": "livre", "inicio": "2026-12-20T19:00"})
    minhas = mundo["pessoa"].get("/minhas").text
    assert "consultorias mensais" in minhas and "consultorias livres" in minhas
    assert "q1" not in minhas, "a anotacao do rastreador apareceu para a pessoa"
    # E a consultoria nao vai para o historico do cla: e 1 para 1.
    assert "marcou consultoria" not in mundo["dono"].get("/historico").text


def test_rastreador_nao_age_em_quem_nao_acompanha(mundo, acompanhando):
    fora = _id_da_pessoa("Outra Teste")
    for url, dados in (
        (f"/rastreador/pessoa/{fora}/tarefas", {"titulo": "invasao"}),
        (f"/rastreador/pessoa/{fora}/saldo", {"mensais": "50", "livres": "50"}),
        (f"/rastreador/pessoa/{fora}/mentorias", {"tipo": "mensal", "inicio": "2026-10-01T10:00"}),
        (f"/rastreador/pessoa/{fora}/anotacao", {"anotacao": "x"}),
    ):
        assert acompanhando.post(url, data=dados).status_code == 404, url


def test_tarefa_da_mentoria_nao_se_apresenta_como_so_sua(mundo, acompanhando):
    """O cartao pessoal diz "So sua". Na tarefa que a mentoria criou isso seria mentira: quem
    acompanha tambem ve. Achado olhando a tela, e nao por teste; este teste impede a volta."""
    import re

    acompanhando.post(
        f"/rastreador/pessoa/{_id_da_pessoa()}/tarefas", data={"titulo": "Cartao rotulo k3"}
    )
    quadro = mundo["pessoa"].get("/minhas").text
    cartao = re.search(r"Cartao rotulo k3</span>\s*<small class=\"cartao-meta\">\s*([^<]*)", quadro)
    assert cartao is not None, "nao achei o cartao da tarefa no quadro"
    assert "Da mentoria" in cartao.group(1)
    assert "Só sua" not in cartao.group(1)


def test_a_pessoa_ajusta_o_proprio_saldo_e_a_rastreadora_ve_quem_mudou(mundo, acompanhando):
    """Decisao do Caio: a pessoa tambem ajusta o proprio saldo. A defesa e a transparencia: o
    ajuste leva o nome dela e aparece na ficha de quem acompanha."""
    from app.database import SessionLocal
    from app.models import Membro
    from app.servicos.mentoria import saldo

    pessoa_id = _id_da_pessoa()
    base = f"/rastreador/pessoa/{pessoa_id}"
    # O bloco de mentoria so aparece para quem ja e acompanhado: a rastreadora marca uma.
    acompanhando.post(f"{base}/mentorias", data={"tipo": "mensal", "inicio": "2026-10-10T18:00"})
    with SessionLocal() as db:
        usadas = saldo(db, db.get(Membro, pessoa_id))["mensal"]["usadas"]

    mundo["pessoa"].post("/minhas/saldo", data={"mensais": "20", "livres": "9"})
    with SessionLocal() as db:
        agora = saldo(db, db.get(Membro, pessoa_id))
    assert agora["mensal"]["total"] == 20 and agora["livre"]["total"] == 9

    # Nao desce abaixo do que ja foi usado, nem por ela.
    abaixo = mundo["pessoa"].post(
        "/minhas/saldo", data={"mensais": str(usadas - 1), "livres": "9"}, follow_redirects=False
    )
    assert "erro_saldo=" in abaixo.headers["location"]

    ficha = _ficha(acompanhando)
    assert "Histórico do saldo" in ficha
    assert "Pessoa Teste ajustou o próprio saldo" in ficha
    # E o ajuste nao vai para o historico do cla: saldo de consultoria nao e assunto do grupo.
    assert "ajustou o próprio saldo" not in mundo["dono"].get("/historico").text
