"""O isolamento entre clas, medido pelo que a API responde.

`test_isolamento.py` ja prova a metade de dentro: nenhuma funcao de `app/repositorios/` devolve
linha de outro cla. Este modulo prova a metade de fora, e prova pela porta nova: o mesmo ataque que
la e feito com formulario e aqui feito com JSON.

Nao e copia por simetria. A API tem uma superficie que o HTML nao tem, e ela e maior de propósito:
metodos que o formulario nao sabe mandar (PUT, DELETE), corpo estruturado onde o form so manda
string, e um `PUT /sessao/cla` que so existe aqui. Cada uma dessas e uma porta a mais para o id do
vizinho entrar, e nenhuma delas e coberta pelo teste de HTML.

A resposta aceitavel e 404, nunca 403. "Existe, mas nao e seu" e meia resposta, e quem varre ids
quer exatamente a outra metade. Para o 404 nao ser trivial, o mesmo id e pedido tambem pela dona
dele, e ali tem que dar 200: sem esse par, um id errado no teste daria 404 por nao existir e a
suite passaria verde sem ter exercitado isolamento nenhum.

O cla vizinho daqui e montado PELA API, do zero, e nao escrito no banco na mao. E o que faz este
modulo provar duas coisas de uma vez: que as rotas de escrita funcionam e que o que elas escreveram
continua invisivel do outro lado.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from app.models import (
    CONCLUIDO,
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

# Strings que so existem no cla vizinho. Se uma delas aparecer numa resposta do cla da Ana, vazou.
SECRETOS = [
    "Cla Vizinho da API",
    "Missao secreta da API",
    "Descartada da API",
    "Gaveta secreta da API",
    "Tarefa secreta da API",
    "Descartada secreta da API",
    "Pia Vizinha",
    "pia@vizinho.com",
]


@pytest.fixture(scope="module")
def vizinho(cliente_de_api, ana, bruno):  # noqa: ARG001
    """Um cla inteiro montado pela API, com dado em todas as tabelas, apagado na saida do modulo.

    Depende de `ana` e `bruno` de propósito, e nao por acidente de ordem alfabetica de arquivo: o
    Bruno entra por um convite que a Ana gera, entao as duas contas tem que existir antes de
    qualquer outro cla aparecer no banco. Pedir as fixtures aqui e o que garante essa ordem.

    A limpeza no fim e obrigatoria, e na ordem das FKs: este e o banco compartilhado da suite, e
    `test_fluxo` e `test_isolamento` contam linhas de ranking e de grafico depois daqui. Teste que
    deixa cla para tras mente na rodada seguinte.
    """
    from app.database import SessionLocal

    pia = cliente_de_api()
    criacao = pia.post(
        "/api/v1/clas",
        json={
            "nome": "Cla Vizinho da API",
            "conta": {
                "nome": "Pia Vizinha",
                "email": "pia@vizinho.com",
                "telefone": "11922220001",
                "senha": "senhaforte1",
            },
        },
    )
    assert criacao.status_code == 201, criacao.text
    sessao = criacao.json()

    missao = pia.post("/api/v1/missoes", json={"titulo": "Missao secreta da API", "pontos": 200})
    assert missao.status_code == 201, missao.text

    descartada = pia.post("/api/v1/missoes", json={"titulo": "Descartada da API", "pontos": 50})
    assert descartada.status_code == 201, descartada.text
    assert pia.delete(f"/api/v1/missoes/{descartada.json()['id']}").status_code == 200

    coluna = pia.post("/api/v1/colunas", json={"nome": "Gaveta secreta da API"})
    assert coluna.status_code == 201, coluna.text

    tarefa = pia.post("/api/v1/tarefas", json={"titulo": "Tarefa secreta da API"})
    assert tarefa.status_code == 201, tarefa.text

    tarefa_lixo = pia.post("/api/v1/tarefas", json={"titulo": "Descartada secreta da API"})
    assert tarefa_lixo.status_code == 201, tarefa_lixo.text
    assert pia.delete(f"/api/v1/tarefas/{tarefa_lixo.json()['id']}").status_code == 200

    convite = pia.post("/api/v1/convites", json={"dias": 7})
    assert convite.status_code == 201, convite.text

    dados = {
        "cliente": pia,
        "cla_id": sessao["cla"]["id"],
        "membro_id": sessao["membro"]["id"],
        "usuario_id": sessao["usuario"]["id"],
        "missao_id": missao.json()["id"],
        "missao_lixeira_id": descartada.json()["id"],
        "coluna_id": coluna.json()["id"],
        "tarefa_id": tarefa.json()["id"],
        "tarefa_lixeira_id": tarefa_lixo.json()["id"],
        "convite_id": convite.json()["id"],
        "convite_token": convite.json()["token"],
    }

    try:
        yield dados
    finally:
        # A ordem e a das FKs, de dentro para fora: missao aponta para o membro que a criou, e
        # membro aponta para o cla. Com PRAGMA foreign_keys=ON, inverter isso estoura no DELETE.
        db = SessionLocal()
        for modelo in (Log, Entrega, TarefaPessoal, Coluna, Convite, Missao, Membro):
            db.execute(delete(modelo).where(modelo.cla_id == dados["cla_id"]))
        db.execute(delete(Cla).where(Cla.id == dados["cla_id"]))
        db.execute(delete(Usuario).where(Usuario.id == dados["usuario_id"]))
        db.commit()
        db.close()


def _pedidos_com_id_alheio(vizinho: dict) -> list[tuple[str, str, dict | None]]:
    """Toda rota da API que recebe id de recurso, com o id do cla vizinho no lugar.

    A lista inclui os quatro verbos porque a superficie de ataque da API e essa: um formulario nao
    consegue mandar PUT nem DELETE, e e justamente por isso que essas rotas nunca passaram pelo
    teste de HTML.
    """
    missao, lixo = vizinho["missao_id"], vizinho["missao_lixeira_id"]
    tarefa, tarefa_lixo = vizinho["tarefa_id"], vizinho["tarefa_lixeira_id"]
    return [
        ("GET", f"/api/v1/missoes/{missao}", None),
        ("PUT", f"/api/v1/missoes/{missao}", {"titulo": "invadido"}),
        ("DELETE", f"/api/v1/missoes/{missao}", None),
        ("PUT", f"/api/v1/missoes/{missao}/entrega", {"status": CONCLUIDO}),
        ("POST", f"/api/v1/historico/missoes/{lixo}/restaurar", None),
        ("POST", f"/api/v1/historico/tarefas/{tarefa_lixo}/restaurar", None),
        ("PUT", f"/api/v1/tarefas/{tarefa}", {"titulo": "invadido"}),
        ("DELETE", f"/api/v1/tarefas/{tarefa}", None),
        ("DELETE", f"/api/v1/colunas/{vizinho['coluna_id']}", None),
        ("DELETE", f"/api/v1/convites/{vizinho['convite_id']}", None),
    ]


def _mandar(cliente, metodo: str, url: str, dados: dict | None):
    """`request` em vez de `.get`/`.delete`: e o unico jeito de mandar corpo num DELETE."""
    return cliente.request(metodo, url, json=dados)


def test_id_do_outro_cla_responde_404_e_nunca_403(ana_api, vizinho):
    """404 e a unica resposta aceitavel. 403 confirmaria que o id existe, que e meia resposta."""
    for metodo, url, dados in _pedidos_com_id_alheio(vizinho):
        resposta = _mandar(ana_api, metodo, url, dados)
        assert resposta.status_code == 404, (
            f"{metodo} {url} respondeu {resposta.status_code}: id de outro cla tem que ser 404"
        )


def test_o_404_nao_e_de_id_inexistente(vizinho):
    """A prova de que os ids acima existem: para quem e do cla deles, as mesmas URLs abrem.

    Sem este par, um id errado no teste daria 404 por nao existir e a suite passaria verde sem ter
    exercitado isolamento nenhum.
    """
    pia = vizinho["cliente"]
    assert pia.get(f"/api/v1/missoes/{vizinho['missao_id']}").status_code == 200

    historico = pia.get("/api/v1/historico")
    assert historico.status_code == 200
    corpo = historico.json()
    assert [m["id"] for m in corpo["missoes"]] == [vizinho["missao_lixeira_id"]]
    assert [t["id"] for t in corpo["tarefas"]] == [vizinho["tarefa_lixeira_id"]]

    assert [c["id"] for c in pia.get("/api/v1/colunas").json()["colunas"]] == [vizinho["coluna_id"]]
    assert [t["id"] for t in pia.get("/api/v1/tarefas").json()["tarefas"]] == [vizinho["tarefa_id"]]
    assert [c["id"] for c in pia.get("/api/v1/convites").json()["convites"]] == [
        vizinho["convite_id"]
    ]


def test_trocar_para_um_cla_de_que_nao_se_participa_da_404(ana_api, vizinho):
    """A rota que so existe na API: trocar de cla escrevendo o id na mao.

    E o pedido mais perigoso do app inteiro, porque um acerto aqui nao vazaria uma linha, vazaria o
    cla inteiro para sempre. O cla do vizinho existe e mesmo assim da 404, igual a um id inventado,
    e a sessao da Ana continua apontando para onde apontava.
    """
    antes = ana_api.get("/api/v1/sessao").json()["cla"]["id"]

    alheio = ana_api.put("/api/v1/sessao/cla", json={"cla_id": vizinho["cla_id"]})
    inventado = ana_api.put("/api/v1/sessao/cla", json={"cla_id": 987654})
    assert alheio.status_code == inventado.status_code == 404
    assert alheio.json() == inventado.json()

    assert ana_api.get("/api/v1/sessao").json()["cla"]["id"] == antes


def test_destino_de_coluna_alheia_e_indistinguivel_de_coluna_que_nao_existe(ana_api, vizinho):
    """Arrastar para a gaveta de outro cla: mesmo codigo e mesmo corpo de um id inventado."""
    alheia = ana_api.post(
        "/api/v1/quadro/mover", json={"destino": f"c{vizinho['coluna_id']}", "itens": []}
    )
    inventada = ana_api.post("/api/v1/quadro/mover", json={"destino": "c987654", "itens": []})
    assert alheia.status_code == inventada.status_code == 400
    assert alheia.json() == inventada.json()


def test_nenhuma_resposta_da_ana_cita_o_cla_vizinho(ana_api, vizinho):  # noqa: ARG001
    """A varredura pelo texto cru: o vazamento que nao passa por id nenhum.

    Os testes acima cobrem o ataque dirigido, com o id na mao. Este cobre o outro, que e o de uma
    consulta esquecer o `where(cla_id)` e derramar o vizinho numa listagem que ninguem pediu. Le o
    JSON como texto de propósito: assim pega o nome do vizinho em qualquer profundidade, inclusive
    num campo que ainda nao existe.
    """
    telas = (
        "/api/v1/painel",
        "/api/v1/quadro",
        "/api/v1/missoes",
        "/api/v1/historico",
        "/api/v1/membros",
        "/api/v1/calendario",
        "/api/v1/colunas",
        "/api/v1/tarefas",
        "/api/v1/convites",
        "/api/v1/sessao",
    )
    for url in telas:
        resposta = ana_api.get(url)
        assert resposta.status_code == 200, f"{url}: {resposta.text}"
        for secreto in SECRETOS:
            assert secreto not in resposta.text, f"{url} mostrou '{secreto}', que e do outro cla"


def test_cada_lado_lista_exatamente_os_proprios_membros(ana_api, vizinho):
    """O isolamento nos dois sentidos, e por numero e nao so por conteudo.

    So a Ana olhando ja seria metade da prova: uma consulta que filtrasse pelo cla errado (e nao
    por nenhum) passaria. Os dois lados olhando, com contagens diferentes, nao passa.
    """
    daqui = [m["nome"] for m in ana_api.get("/api/v1/membros").json()["membros"]]
    de_la = [m["nome"] for m in vizinho["cliente"].get("/api/v1/membros").json()["membros"]]
    assert sorted(daqui) == ["Ana Tester", "Bruno Tester"]
    assert de_la == ["Pia Vizinha"]


def test_o_pedido_recusado_nao_deixou_marca_no_outro_cla(ana_api, vizinho):
    """404 depois do estrago nao vale: o pedido recusado nao pode ter escrito nada.

    Roda depois do sweep de propósito (as funcoes acima ja mandaram editar, excluir, restaurar e
    concluir), repete o sweep para nao depender da ordem em que o pytest resolveu rodar, e le o
    banco direto em vez de perguntar pela propria API: se a leitura estivesse quebrada do mesmo
    jeito que a escrita, perguntar para ela seria conferir o erro com o proprio erro.
    """
    from app.database import SessionLocal

    for metodo, url, dados in _pedidos_com_id_alheio(vizinho):
        if metodo != "GET":
            _mandar(ana_api, metodo, url, dados)

    cla_id = vizinho["cla_id"]
    with SessionLocal() as db:
        missao = db.get(Missao, vizinho["missao_id"])
        assert missao is not None and missao.excluida_em is None
        assert missao.titulo == "Missao secreta da API"

        missao_lixo = db.get(Missao, vizinho["missao_lixeira_id"])
        assert missao_lixo is not None and missao_lixo.excluida_em is not None

        tarefa = db.get(TarefaPessoal, vizinho["tarefa_id"])
        assert tarefa is not None and tarefa.titulo == "Tarefa secreta da API"

        tarefa_lixo = db.get(TarefaPessoal, vizinho["tarefa_lixeira_id"])
        assert tarefa_lixo is not None and tarefa_lixo.excluida_em is not None

        assert db.get(Coluna, vizinho["coluna_id"]) is not None

        convite = db.get(Convite, vizinho["convite_id"])
        assert convite is not None and convite.revogado_em is None

        # A tentativa de concluir a missao do vizinho nao pode ter criado entrega em cla nenhum.
        assert db.scalar(select(func.count(Entrega.id)).where(Entrega.cla_id == cla_id)) == 0
        assert (
            db.scalar(
                select(func.count(Entrega.id)).where(Entrega.missao_id == vizinho["missao_id"])
            )
            == 0
        )
