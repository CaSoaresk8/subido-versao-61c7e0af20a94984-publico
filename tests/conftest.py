"""Ambiente dos testes ponta a ponta.

O app le DATA_DIR e DATABASE_URL na importacao de app.config, entao as variaveis precisam estar no
ambiente ANTES de qualquer import de app.*. Por isso ficam aqui no topo do conftest, que o pytest
carrega antes dos modulos de teste, e nao dentro de uma fixture.

O banco e um arquivo novo num diretorio temporario proprio, criado na entrada e apagado na saida.
Teste que deixa estado para tras mente na rodada seguinte: passa hoje por causa do que sobrou de
ontem, ou falha sozinho sem ninguem ter mexido em nada.

O cla tem exatamente duas pessoas, Ana e Bruno, e isso e proposital: varias assercoes contam
linhas do ranking e do grafico ("1 de 2"). Criar uma terceira conta NO CLA DA ANA em qualquer teste
quebra essas contagens, e nao existe rota para apagar membro. Teste de criacao de conta que precise
falhar usa email novo e espera 400, que nao cria ninguem.

Quem precisa exercitar entrada de gente (convite aceito, uso esgotado, troca de cla ativo) usa o
cla da Carla, que existe so para isso: ele e um segundo cla de verdade, e membro que entra nele nao
aparece em contagem nenhuma do cla da Ana. Se isolamento estiver quebrado, esses testes contaminam
as contagens da Ana, o que e uma forma de descobrir por acidente que ele quebrou.

A montagem das duas contas passa pelas portas de verdade do app: a Ana entra criando um cla, e o
Bruno entra por um convite que a Ana gerou. Nao ha atalho de fixture escrevendo direto no banco,
porque a porta de entrada e justamente o que mudou na fase 3: se ela quebrar, a suite inteira nao
sobe, em vez de passar verde em cima de um cenario montado por baixo.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="copyecola-teste-"))
os.environ["DATA_DIR"] = str(TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{TMP / 'teste.db'}"
os.environ["SECRET_KEY"] = "teste"


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def app_web():
    # Importado aqui dentro, e nao no topo, para garantir que as variaveis acima ja valem.
    from app.main import app

    return app


NOME_DO_CLA = "Cla de Teste"


def _gerar_convite(cliente, **campos) -> tuple[int, str]:
    """Gera um convite no cla ativo de `cliente` e devolve (id, token), lidos da propria tela.

    Le a pagina em vez de consultar o banco de proposito: o que precisa funcionar e o link que a
    pessoa copia da tela, e um teste que pegasse o token pelo banco passaria mesmo se a tela nunca
    mostrasse o link.
    """
    import re

    criacao = cliente.post("/cla/convites", data=campos, follow_redirects=False)
    assert criacao.status_code == 303, criacao.text
    destino = criacao.headers["location"]
    # O id vem do proprio redirect em vez de ser procurado na lista: com varios convites validos no
    # mesmo cla, qualquer heuristica de "o primeiro da lista" acabaria testando o convite errado.
    achado_id = re.search(r"gerado=(\d+)", destino)
    assert achado_id is not None, f"o redirect nao trouxe o id do convite: {destino}"

    pagina = cliente.get(destino)
    # `autofocus` e a marca que a tela poe no convite que acabou de sair.
    achado = re.search(r'value="[^"]*/convite/([\w-]+)"[^>]*autofocus', pagina.text)
    assert achado is not None, "a tela do cla nao destacou o link do convite recem gerado"
    return int(achado_id.group(1)), achado.group(1)


@pytest.fixture(scope="session")
def gerar_convite():
    """Entrega o helper acima como fixture, para nenhum teste precisar importar este arquivo.

    `from tests.conftest import ...` criaria um SEGUNDO modulo conftest, e o topo deste tem efeito
    colateral: ele cria um diretorio temporario e reescreve DATA_DIR e DATABASE_URL. A segunda
    execucao apontaria o ambiente para um banco que o app nem abriu, e deixaria a pasta para tras
    no fim da rodada, que e exatamente o tipo de estado que faz a rodada seguinte mentir.
    """
    return _gerar_convite


@pytest.fixture(scope="session")
def criacao_ana(app_web):
    """A Ana cria o cla, e e por isso que ela existe: quem abre um cla vira o primeiro membro dele.

    Devolve a resposta junto porque ela e a prova de que a porta funciona ponta a ponta: sai do
    formulario e cai no dashboard logado, sem passo intermediario de login.
    """
    from fastapi.testclient import TestClient

    cliente = TestClient(app_web)
    resposta = cliente.post(
        "/criar-cla",
        data={
            "nome_cla": NOME_DO_CLA,
            "nome": "Ana Tester",
            "email": "ana@cla.com",
            # Escrito com pontuacao de proposito: e assim que uma pessoa digita, e o caminho que a
            # fixture exercita tem que ser o mesmo que o formulario de verdade recebe.
            "telefone": "(11) 98765-0001",
            "senha": "senhaforte1",
        },
        follow_redirects=True,
    )
    return cliente, resposta


@pytest.fixture(scope="session")
def ana(criacao_ana):
    return criacao_ana[0]


@pytest.fixture(scope="session")
def bruno(app_web, ana):
    """O Bruno entra pela outra porta: convite gerado pela Ana, conta criada no mesmo passo."""
    from fastapi.testclient import TestClient

    _, token = _gerar_convite(ana, dias=7, max_usos="")
    cliente = TestClient(app_web)
    resposta = cliente.post(
        f"/convite/{token}",
        data={
            "nome": "Bruno Tester",
            "email": "bruno@cla.com",
            "telefone": "11987650002",
            "senha": "senhaforte1",
        },
        follow_redirects=True,
    )
    assert "Dashboard do clã" in resposta.text, "o convite nao colocou o Bruno dentro do cla"
    return cliente


@pytest.fixture(scope="session")
def carla(app_web):
    """Dona de um SEGUNDO cla, onde os testes podem fazer gente entrar sem mexer no cla da Ana."""
    from fastapi.testclient import TestClient

    cliente = TestClient(app_web)
    cliente.post(
        "/criar-cla",
        data={
            "nome_cla": "Cla da Carla",
            "nome": "Carla Tester",
            "email": "carla@cla.com",
            "telefone": "11987650003",
            "senha": "senhaforte1",
        },
        follow_redirects=True,
    )
    return cliente


@pytest.fixture(scope="session")
def visitante(app_web):
    """Cliente que nunca faz login. O Chrome busca manifesto e service worker assim."""
    from fastapi.testclient import TestClient

    return TestClient(app_web)


@pytest.fixture(scope="session")
def mundo():
    """Ids que um passo do fluxo cria e o seguinte usa (missao, coluna, tarefa)."""
    return {}


# --- API -------------------------------------------------------------------------------------
#
# Toda rota que escreve na API exige o cabecalho X-Requested-With. O TestClient aceita headers
# fixos no construtor, entao o cliente de API ja nasce com ele em todo pedido: teste nenhum
# precisa lembrar de repetir isso, e o teste que prova a recusa (test_api_contrato) usa um
# cliente SEM o header, de proposito.
#
# O valor do header nao importa e nao e conferido em lugar nenhum: a prova e ele EXISTIR, porque
# um formulario de outro site nao consegue mandar cabecalho nenhum.

CABECALHO_DE_ORIGEM = {"X-Requested-With": "teste"}


def _cliente_de_api(app_web):
    from fastapi.testclient import TestClient

    return TestClient(app_web, headers=CABECALHO_DE_ORIGEM)


@pytest.fixture(scope="session")
def cliente_de_api(app_web):
    """Fabrica de clientes de API: cada chamada devolve um TestClient novo, sem sessao.

    E fabrica e nao cliente pronto porque os testes de API montam clas proprios e precisam de um
    cliente por pessoa. Cada TestClient guarda os proprios cookies, e dois deles no mesmo teste
    e o que permite olhar o mesmo cla por duas sessoes diferentes.
    """
    return lambda: _cliente_de_api(app_web)


@pytest.fixture(scope="session")
def ana_api(app_web, ana):  # noqa: ARG001
    """A Ana, logada pela API em vez do formulario.

    Depende de `ana` porque e essa fixture que cria a conta dela; aqui so se faz o login. A sessao
    e outra (outro TestClient, outro cookie), e isso e de proposito: a mesma conta vista pelas duas
    interfaces e o que as fases 5 e 6 vao precisar que funcione.
    """
    cliente = _cliente_de_api(app_web)
    entrada = cliente.post("/api/v1/sessao", json={"email": "ana@cla.com", "senha": "senhaforte1"})
    assert entrada.status_code == 200, entrada.text
    return cliente


@pytest.fixture(autouse=True)
def _limites_zerados():
    """Os limitadores sao globais do processo (contam em memoria, por IP).

    Sem zerar entre os testes, um arquivo que erra senha de proposito deixaria o IP do cliente de
    teste bloqueado para os proximos, e a suite comecaria a falhar por ordem de execucao, que e o
    pior tipo de teste vermelho: o que muda de lugar a cada rodada.
    """
    from app.servicos import limites

    for limitador in (limites.senha, limites.cadastro, limites.video):
        limitador.esquecer_tudo()
    yield
