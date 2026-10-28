"""A agenda do cla, de ponta a ponta pela tela, com um Google de mentira no lugar da rede.

**Este arquivo monta um cla proprio**, pelo mesmo motivo do `test_api_fluxo.py`: o cla da Ana tem
contagens exatas que outros arquivos conferem, e evento e log escritos la quebrariam aquelas
contagens sem quebrar regra nenhuma. Tudo e apagado na entrada e na saida, pelo email marcador.

O que se prova aqui e o lado do app (o que ele manda ao Google, para quem, e o que faz com cada
resposta). Que o Google de verdade aceita o formato e manda o email e conferido conectando uma
conta real, e nao ha teste automatico que substitua isso.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.servicos import google_agenda
from tests.google_falso import GoogleFalso

MARCA = "agenda-teste.local"
CAIO = f"caio@{MARCA}"
DUDA = f"duda@{MARCA}"
ENZO = f"enzo@{MARCA}"
CONTA_GOOGLE = f"convites@{MARCA}"
LIA = f"lia@{MARCA}"
NOME_DO_CLA = "Cla da Agenda"
OUTRO_CLA = "Outro Cla da Agenda"
CABECALHO = {"X-Requested-With": "teste"}


def _limpar() -> None:
    """De dentro para fora, pela ordem das FKs compostas. Acha o cla pelo email marcador."""
    from sqlalchemy import delete, select

    from app.database import SessionLocal
    from app.models import (
        Cla,
        Coluna,
        Convite,
        Entrega,
        Evento,
        IntegracaoGoogle,
        Log,
        Membro,
        Missao,
        TarefaPessoal,
        Usuario,
    )

    db = SessionLocal()
    contas = list(db.scalars(select(Usuario.id).where(Usuario.email.like(f"%@{MARCA}"))))
    clas = list(db.scalars(select(Membro.cla_id).where(Membro.usuario_id.in_(contas)).distinct()))
    # A conta Google e da plataforma e aponta para o usuario que conectou, nao para um cla.
    db.execute(
        delete(IntegracaoGoogle).where(IntegracaoGoogle.conectado_por_usuario_id.in_(contas))
    )
    for modelo in (Log, Evento, Entrega, TarefaPessoal, Coluna, Convite, Missao, Membro):
        db.execute(delete(modelo).where(modelo.cla_id.in_(clas)))
    db.execute(delete(Cla).where(Cla.id.in_(clas)))
    db.execute(delete(Usuario).where(Usuario.id.in_(contas)))
    db.commit()
    db.close()


def _entrar(app_web, token: str, nome: str, email: str) -> TestClient:
    cliente = TestClient(app_web)
    resposta = cliente.post(
        f"/convite/{token}",
        data={"nome": nome, "email": email, "telefone": "11900001111", "senha": "senhaforte1"},
        follow_redirects=False,
    )
    assert resposta.status_code == 303, resposta.text
    return cliente


@pytest.fixture(scope="module")
def cla_agenda(app_web, gerar_convite):
    _limpar()
    caio = TestClient(app_web)
    criacao = caio.post(
        "/criar-cla",
        data={
            "nome_cla": NOME_DO_CLA,
            "nome": "Caio Teste",
            "email": CAIO,
            "telefone": "11900000000",
            "senha": "senhaforte1",
        },
        follow_redirects=False,
    )
    assert criacao.status_code == 303, criacao.text
    _, token = gerar_convite(caio, dias=7, max_usos="")
    duda = _entrar(app_web, token, "Duda Teste", DUDA)
    # Um segundo cla, com outra pessoa, para provar que a conta unica nao mistura convidados.
    lia = TestClient(app_web)
    outro = lia.post(
        "/criar-cla",
        data={
            "nome_cla": OUTRO_CLA,
            "nome": "Lia Teste",
            "email": LIA,
            "telefone": "11900002222",
            "senha": "senhaforte1",
        },
        follow_redirects=False,
    )
    assert outro.status_code == 303, outro.text
    try:
        yield {"caio": caio, "duda": duda, "lia": lia, "app": app_web, "token": token}
    finally:
        _limpar()


@pytest.fixture
def google(monkeypatch):
    """Troca a rede pelo Google de mentira e liga a configuracao, so durante o teste."""
    falso = GoogleFalso(email=CONTA_GOOGLE)
    monkeypatch.setattr(google_agenda, "transporte", falso)
    monkeypatch.setattr(google_agenda, "GOOGLE_CLIENT_ID", "id-de-teste")
    monkeypatch.setattr(google_agenda, "segredo_google", lambda: "segredo-de-teste")
    monkeypatch.setattr("app.routers.agenda.GOOGLE_CONFIGURADO", True)
    # O Caio e o dono da plataforma nestes testes; a Duda e a Lia sao membros comuns.
    monkeypatch.setattr("app.servicos.agenda.DONOS_DA_PLATAFORMA", frozenset({CAIO}))
    # O cache de access token e do processo: sem limpar, um teste herdaria o acesso do anterior e
    # nunca chegaria a pedir renovacao, que e justamente onde a permissao retirada aparece.
    google_agenda._acessos.clear()
    yield falso
    google_agenda._acessos.clear()


def _quando(dias: int, hora: int = 20) -> str:
    alvo = datetime.now() + timedelta(days=dias)
    return alvo.replace(hour=hora, minute=0).strftime("%Y-%m-%dT%H:%M")


def _marcar(cliente, titulo: str, dias: int = 5, **extra) -> int:
    dados = {"titulo": titulo, "tipo": "reuniao", "inicio": _quando(dias), "duracao_min": "60"}
    dados.update(extra)
    resposta = cliente.post("/agenda/novo", data=dados, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text
    return int(resposta.headers["location"].rsplit("/", 1)[1])


def _conectar(cliente, falso: GoogleFalso):
    ida = cliente.get("/agenda/google/conectar", follow_redirects=False)
    assert ida.status_code == 303
    destino = urllib.parse.urlsplit(ida.headers["location"])
    assert destino.netloc == "accounts.google.com"
    parametros = urllib.parse.parse_qs(destino.query)
    assert parametros["access_type"] == ["offline"] and parametros["prompt"] == ["consent"]
    assert "calendar.events" in parametros["scope"][0]
    state = parametros["state"][0]
    return cliente.get(f"/agenda/google/retorno?state={state}&code=codigo1", follow_redirects=False)


def _evento_no_banco(evento_id: int):
    from app.database import SessionLocal
    from app.models import Evento

    with SessionLocal() as db:
        return db.get(Evento, evento_id)


# ---------------------------------------------------------------------------------------------
# Sem Google: a agenda funciona sozinha
# ---------------------------------------------------------------------------------------------


def test_sem_conta_google_o_evento_e_marcado_e_todo_mundo_ve(cla_agenda):
    evento_id = _marcar(
        cla_agenda["caio"], "Reuniao de alinhamento", local="https://meet.google.com/abc"
    )
    pagina = cla_agenda["duda"].get(f"/agenda/{evento_id}")
    assert pagina.status_code == 200
    assert "Reuniao de alinhamento" in pagina.text
    assert "o envio ainda não foi ativado" in pagina.text
    assert "calendar.google.com/calendar/render" in pagina.text, "falta o adicionar a minha agenda"
    assert "Reuniao de alinhamento" in cla_agenda["duda"].get("/agenda").text
    assert _evento_no_banco(evento_id).google_status == ""


def test_formulario_recusa_e_devolve_o_que_foi_digitado(cla_agenda):
    caio = cla_agenda["caio"]
    casos = [
        ({"titulo": "ab", "inicio": _quando(3)}, "Escreva um título"),
        ({"titulo": "Sem data", "inicio": ""}, "Escolha o dia e a hora"),
        ({"titulo": "Duracao torta", "inicio": _quando(3), "duracao_min": "5"}, "A duração vai"),
        ({"titulo": "Tipo torto", "inicio": _quando(3), "tipo": "festa"}, "Escolha o tipo"),
        (
            {"titulo": "Quem conduz", "inicio": _quando(3), "conduzido_por_id": "999999"},
            "alguém do clã",
        ),
    ]
    for dados, frase in casos:
        dados = {
            "tipo": "reuniao",
            "duracao_min": "60",
            "descricao": "pauta que nao pode sumir",
            **dados,
        }
        resposta = caio.post("/agenda/novo", data=dados)
        assert resposta.status_code == 400, dados
        assert frase in resposta.text, (frase, dados)
        assert "pauta que nao pode sumir" in resposta.text, "o erro apagou o que a pessoa escreveu"


# ---------------------------------------------------------------------------------------------
# Conectar a conta que manda os convites
# ---------------------------------------------------------------------------------------------


def test_so_o_dono_da_plataforma_conecta_e_desconecta(cla_agenda, google):
    """A conta serve a todos os clas: um membro comum trocando-a mudaria o remetente de todo mundo.

    404, como todo "nao e seu" do app. E a tela nem oferece o botao para quem nao e dono.
    """
    duda = cla_agenda["duda"]
    assert duda.get("/agenda/google/conectar", follow_redirects=False).status_code == 404
    assert duda.get("/agenda/google/retorno?state=x&code=y").status_code == 404
    assert duda.post("/agenda/google/desconectar").status_code == 404
    assert "/agenda/google/conectar" not in duda.get("/agenda").text
    assert "Conectar conta Google" in cla_agenda["caio"].get("/agenda").text


def test_retorno_do_google_sem_o_state_da_sessao_e_recusado(cla_agenda, google):
    """O link de retorno forjado: codigo valido de OUTRA conta, sem ter passado pelo conectar."""
    resposta = cla_agenda["caio"].get(
        "/agenda/google/retorno?state=inventado&code=de-fora", follow_redirects=False
    )
    assert resposta.headers["location"] == "/agenda?google=expirou"
    assert not [c for c in google.chamadas if c[1] == google_agenda.URL_TOKEN]


def test_consentimento_sem_a_caixa_da_agenda_nao_conecta(cla_agenda, google):
    google.escopo_concedido = "openid email"
    resposta = _conectar(cla_agenda["caio"], google)
    assert resposta.headers["location"] == "/agenda?google=erro"
    tela = cla_agenda["caio"].get("/agenda?google=erro").text
    assert "permissão de agenda não foi marcada" in tela
    assert "Conectar conta Google" in tela, "o cla nao pode ficar como conectado"


def test_conectar_convida_o_cla_para_o_que_ja_estava_marcado(cla_agenda, google):
    antes = _marcar(cla_agenda["duda"], "Workshop de criativos", dias=8, tipo="workshop")
    resposta = _conectar(cla_agenda["caio"], google)
    assert resposta.headers["location"] == "/agenda?google=conectado"

    convites = [e for e in google.ativos() if e["summary"] == "Workshop de criativos"]
    assert len(convites) == 1, "o evento marcado antes de conectar nao virou convite"
    convite = convites[0]
    emails = sorted(c["email"] for c in convite["attendees"])
    assert emails == [CAIO, DUDA]
    assert convite["guestsCanSeeOtherGuests"] is False, "convidado veria o email dos outros"
    assert convite["start"]["timeZone"] == "America/Sao_Paulo"
    assert _evento_no_banco(antes).google_status == "enviado"

    from app.database import SessionLocal
    from app.models import IntegracaoGoogle

    with SessionLocal() as db:
        guardada = db.query(IntegracaoGoogle).one()
    assert "refresh-codigo1" not in guardada.token_cifrado, "o token foi guardado em texto puro"
    assert google_agenda.decifrar(guardada.token_cifrado) == "refresh-codigo1"
    # O dono ve qual conta envia; a Duda, que e membro comum, ve que existe uma e mais nada.
    assert CONTA_GOOGLE in cla_agenda["caio"].get("/agenda").text
    tela_duda = cla_agenda["duda"].get("/agenda").text
    assert CONTA_GOOGLE not in tela_duda, "o email de quem envia vazou para um membro comum"
    assert "Convites por e-mail" not in tela_duda
    assert "por uma conta da plataforma" not in tela_duda


def test_uma_conta_para_todos_os_clas_e_cada_convite_so_para_o_proprio_cla(cla_agenda, google):
    """A pergunta que definiu o desenho: com UMA conta para a plataforma, o evento do cla A convida
    so o cla A, e o do cla B so o cla B. Nem na lista de convidados, nem na agenda do app, um cla
    enxerga o outro."""
    _conectar(cla_agenda["caio"], google)
    do_a = _marcar(cla_agenda["duda"], "Reuniao so do cla A")
    do_b = _marcar(cla_agenda["lia"], "Reuniao so do cla B")

    convite_a = next(e for e in google.ativos() if e["summary"] == "Reuniao so do cla A")
    convite_b = next(e for e in google.ativos() if e["summary"] == "Reuniao so do cla B")
    assert sorted(c["email"] for c in convite_a["attendees"]) == [CAIO, DUDA]
    assert [c["email"] for c in convite_b["attendees"]] == [LIA]

    assert "Reuniao so do cla B" not in cla_agenda["duda"].get("/agenda").text
    assert "Reuniao so do cla A" not in cla_agenda["lia"].get("/agenda").text
    assert cla_agenda["lia"].get(f"/agenda/{do_a}").status_code == 404
    assert cla_agenda["duda"].get(f"/agenda/{do_b}").status_code == 404
    # A Lia, de outro cla e sem ser dona, ve de onde o convite vem, e so isso.
    tela_lia = cla_agenda["lia"].get("/agenda").text
    assert CONTA_GOOGLE not in tela_lia, "o email de quem envia vazou para outro cla"
    assert "/agenda/google/desconectar" not in tela_lia


def test_conectar_convida_todos_os_clas_para_o_que_ja_estava_marcado(cla_agenda, google):
    from app.database import SessionLocal
    from app.models import IntegracaoGoogle

    with SessionLocal() as db:
        db.query(IntegracaoGoogle).delete()
        db.commit()
    _marcar(cla_agenda["lia"], "Marcado no B antes de conectar", dias=9)
    _conectar(cla_agenda["caio"], google)
    convite = next(e for e in google.ativos() if e["summary"] == "Marcado no B antes de conectar")
    assert [c["email"] for c in convite["attendees"]] == [LIA]


def test_quem_conectou_nao_se_convida(cla_agenda, google):
    """A conta dos convites e o organizador: na lista de convidados ela so faria barulho."""
    google.email = CAIO
    _conectar(cla_agenda["caio"], google)
    _marcar(cla_agenda["caio"], "Reuniao do organizador")
    convite = next(e for e in google.ativos() if e["summary"] == "Reuniao do organizador")
    assert [c["email"] for c in convite["attendees"]] == [DUDA]


# ---------------------------------------------------------------------------------------------
# O ciclo de vida do convite
# ---------------------------------------------------------------------------------------------


def test_editar_atualiza_o_mesmo_convite_sem_apagar_quem_confirmou(cla_agenda, google):
    _conectar(cla_agenda["caio"], google)
    evento_id = _marcar(cla_agenda["caio"], "Reuniao semanal")
    google_id = _evento_no_banco(evento_id).google_evento_id
    google.responder(google_id, DUDA, "accepted")

    resposta = cla_agenda["duda"].post(
        f"/agenda/{evento_id}/editar",
        data={
            "titulo": "Reuniao semanal (nova hora)",
            "tipo": "reuniao",
            "inicio": _quando(5, hora=21),
            "duracao_min": "90",
        },
        follow_redirects=False,
    )
    assert resposta.status_code == 303
    assert _evento_no_banco(evento_id).google_evento_id == google_id, "mandou um convite novo"
    atualizado = google.eventos[google_id]
    assert atualizado["summary"] == "Reuniao semanal (nova hora)"
    assert atualizado["start"]["dateTime"].endswith("T21:00")
    duda = next(c for c in atualizado["attendees"] if c["email"] == DUDA)
    assert duda["responseStatus"] == "accepted", "a edicao apagou o Sim de quem confirmou"


def test_excluir_cancela_e_restaurar_convida_de_novo(cla_agenda, google):
    _conectar(cla_agenda["caio"], google)
    evento_id = _marcar(cla_agenda["caio"], "Encontro que vai e volta")
    google_id = _evento_no_banco(evento_id).google_evento_id

    cla_agenda["duda"].post(f"/agenda/{evento_id}/excluir")
    assert google.eventos[google_id]["status"] == "cancelled"
    assert cla_agenda["caio"].get(f"/agenda/{evento_id}").status_code == 404
    assert "Encontro que vai e volta" in cla_agenda["caio"].get("/historico").text

    cla_agenda["caio"].post(f"/historico/eventos/{evento_id}/restaurar")
    novo_id = _evento_no_banco(evento_id).google_evento_id
    assert novo_id != google_id, "restaurar reaproveitou um convite cancelado"
    assert google.eventos[novo_id]["status"] == "confirmed"
    assert _evento_no_banco(evento_id).google_status == "enviado"


def test_evento_apagado_direto_no_google_volta_a_existir_na_edicao(cla_agenda, google):
    _conectar(cla_agenda["caio"], google)
    evento_id = _marcar(cla_agenda["caio"], "Apagado por fora")
    google.apagar_por_fora(_evento_no_banco(evento_id).google_evento_id)
    cla_agenda["caio"].post(f"/agenda/{evento_id}/reenviar")
    assert any(e["summary"] == "Apagado por fora" for e in google.ativos())
    assert _evento_no_banco(evento_id).google_status == "enviado"


# ---------------------------------------------------------------------------------------------
# Falhas: o Google nunca derruba o app
# ---------------------------------------------------------------------------------------------


def test_google_fora_do_ar_salva_o_evento_e_deixa_tentar_de_novo(cla_agenda, google):
    _conectar(cla_agenda["caio"], google)
    google.falhar_com = 500
    evento_id = _marcar(cla_agenda["caio"], "Marcado com o Google caido")
    salvo = _evento_no_banco(evento_id)
    assert salvo is not None and salvo.google_status == "erro"
    pagina = cla_agenda["caio"].get(f"/agenda/{evento_id}").text
    assert "Convite não enviado" in pagina and "Tentar enviar de novo" in pagina
    assert "convite não enviado" in cla_agenda["caio"].get("/agenda").text

    google.falhar_com = None
    cla_agenda["caio"].post(f"/agenda/{evento_id}/reenviar")
    assert _evento_no_banco(evento_id).google_status == "enviado"


def test_permissao_retirada_pede_para_conectar_de_novo(cla_agenda, google):
    _conectar(cla_agenda["caio"], google)
    google_agenda._acessos.clear()
    google.sem_permissao = True
    evento_id = _marcar(cla_agenda["caio"], "Depois de tirar a permissao")
    salvo = _evento_no_banco(evento_id)
    assert salvo.google_status == "erro"
    assert "Conecte a conta de novo" in salvo.google_erro


def test_desconectar_revoga_o_acesso_no_google(cla_agenda, google):
    _conectar(cla_agenda["caio"], google)
    # Conectar por cima de uma conta anterior do modulo ja revoga a antiga; o que importa aqui e o
    # que o desconectar acrescenta.
    antes = len(google.revogados)
    cla_agenda["caio"].post("/agenda/google/desconectar")
    assert google.revogados[antes:] == ["refresh-codigo1"]
    assert "Conectar conta Google" in cla_agenda["caio"].get("/agenda").text


# ---------------------------------------------------------------------------------------------
# Quem entra depois, calendario, feed
# ---------------------------------------------------------------------------------------------


def test_quem_entra_no_cla_passa_a_ser_convidado_do_que_vem(cla_agenda, google):
    _conectar(cla_agenda["caio"], google)
    evento_id = _marcar(cla_agenda["caio"], "Reuniao depois do Enzo entrar", dias=10)
    google_id = _evento_no_banco(evento_id).google_evento_id
    _entrar(cla_agenda["app"], cla_agenda["token"], "Enzo Teste", ENZO)
    convidados = [c["email"] for c in google.eventos[google_id]["attendees"]]
    assert ENZO in convidados, "quem entrou depois ficou fora do convite"


def test_evento_aparece_no_calendario_do_painel_no_dia_e_hora(cla_agenda, google):
    alvo = datetime.now() + timedelta(days=2)
    evento_id = _marcar(cla_agenda["caio"], "Aparece no calendario", dias=2)
    painel = cla_agenda["duda"].get(f"/?ano={alvo.year}&mes={alvo.month}").text
    assert re.search(rf'href="/agenda/{evento_id}"[^>]*>20:00 Aparece no calendario', painel)
    agenda = cla_agenda["duda"].get(f"/agenda?ano={alvo.year}&mes={alvo.month}")
    assert agenda.status_code == 200
    assert 'cal-evento-popover' in agenda.text
    assert 'agenda-ampliada' in agenda.text
    assert '/static/agenda-previa.js' in agenda.text
    assert 'Adicionar à minha agenda' in agenda.text
    assert 'Abrir evento' not in agenda.text
    assert f'class="cal-evento-link" href="/agenda/{evento_id}"' in agenda.text
    assert 'calendar.google.com/calendar/render' in agenda.text
    assert '20:00 Aparece no calendario' in agenda.text


def test_evento_entra_no_feed_do_cla(cla_agenda, google):
    _marcar(cla_agenda["caio"], "Vai para o feed")
    assert "Vai para o feed" in cla_agenda["duda"].get("/historico").text


def test_api_da_agenda_segue_as_mesmas_regras(cla_agenda, app_web, google):
    """A API usa o cookie de quem ja entrou pela tela; o cabecalho e a prova de origem propria."""
    api = TestClient(app_web, headers=CABECALHO, cookies=cla_agenda["duda"].cookies)
    criado = api.post(
        "/api/v1/agenda",
        json={"titulo": "Pela API", "inicio": _quando(6), "tipo": "workshop", "duracao_min": 45},
    )
    assert criado.status_code == 201, criado.text
    corpo = criado.json()
    assert corpo["inicio"].endswith("T20:00") and corpo["fim"].endswith("T20:45")
    assert "email" not in str(corpo.get("conduzido_por"))
    assert api.post("/api/v1/agenda", json={"titulo": "x", "inicio": _quando(6)}).status_code == 400
    assert any(e["titulo"] == "Pela API" for e in api.get("/api/v1/agenda").json()["eventos"])
    assert api.delete(f"/api/v1/agenda/{corpo['id']}").json()["ativo"] is False
    restaurado = api.post(f"/api/v1/historico/eventos/{corpo['id']}/restaurar")
    assert restaurado.json()["ativo"] is True


def test_o_email_de_quem_envia_nao_vaza_para_membro_nem_pela_api(cla_agenda, google, app_web):
    """O endereco de quem organiza aparece no convite do Google, e isso ninguem muda. Dentro do app
    ele nao precisa aparecer, e sao 19 clas de gente que nao se conhece: fica so para o dono."""
    _conectar(cla_agenda["caio"], google)
    evento_id = _marcar(cla_agenda["caio"], "Reuniao com convite enviado")

    membro = TestClient(app_web, headers=CABECALHO, cookies=cla_agenda["duda"].cookies)
    conta = membro.get("/api/v1/agenda").json()["google"]["conta"]
    assert conta["conectada"] is True, "o membro precisa saber que o convite sai"
    assert conta["email"] is None, "a API entregou o email de quem envia para um membro comum"

    dono = TestClient(app_web, headers=CABECALHO, cookies=cla_agenda["caio"].cookies)
    assert dono.get("/api/v1/agenda").json()["google"]["conta"]["email"] == CONTA_GOOGLE

    detalhe = cla_agenda["duda"].get(f"/agenda/{evento_id}").text
    assert "convite enviado" in detalhe
    assert CONTA_GOOGLE not in detalhe, "o email vazou na tela do evento"


def test_com_a_agenda_desligada_ela_nao_existe_para_ninguem(cla_agenda, app_web, monkeypatch, google):
    """`AGENDA_ATIVA=0` e como a agenda sobe em producao ate o app do Google ser publicado.

    Desligada, nada dela pode aparecer: menu, paginas, API, calendario e lixeira. Um item de menu
    que leva a um 404, ou um evento no calendario que nao abre, seria pior do que a agenda nao
    existir.
    """
    from datetime import datetime, timedelta

    # Um evento criado com a agenda ligada, para provar que ele some quando ela desliga.
    evento_id = _marcar(cla_agenda["caio"], "Some com a agenda desligada", dias=2)
    alvo = datetime.now() + timedelta(days=2)

    monkeypatch.setattr("app.config.AGENDA_ATIVA", False)
    caio = cla_agenda["caio"]
    assert caio.get("/agenda").status_code == 404
    assert caio.get(f"/agenda/{evento_id}").status_code == 404
    assert caio.get("/agenda/google/conectar", follow_redirects=False).status_code == 404
    assert caio.post(f"/historico/eventos/{evento_id}/restaurar").status_code == 404
    api = TestClient(app_web, headers=CABECALHO, cookies=caio.cookies)
    assert api.get("/api/v1/agenda").status_code == 404

    painel = caio.get(f"/?ano={alvo.year}&mes={alvo.month}").text
    assert 'href="/agenda"' not in painel, "o menu ainda leva para a agenda"
    assert "Some com a agenda desligada" not in painel, "o evento continua no calendario"
    assert "Eventos excluídos" not in caio.get("/historico").text

    # Ligando de novo, tudo volta: nada foi apagado, so escondido.
    monkeypatch.setattr("app.config.AGENDA_ATIVA", True)
    assert caio.get(f"/agenda/{evento_id}").status_code == 200
    assert 'href="/agenda"' in caio.get("/").text
