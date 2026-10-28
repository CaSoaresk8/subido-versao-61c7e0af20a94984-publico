"""A gemea de `test_fluxo.py` em JSON: a mesma narrativa, pela API.

Cada teste daqui tem um irmao em `test_fluxo.py` provando a mesma regra pela tela. As duas metades
ficam verdes juntas durante as fases 5 e 6, e so as de HTML sao apagadas no corte. E por isso que a
ordem e os nomes acompanham o outro arquivo de perto: quando uma das duas quebrar, a que sobrou
diz se o defeito e da regra ou so da interface.

**Este arquivo monta um cla proprio.** Nao e capricho de organizacao: o pytest roda os arquivos em
ordem alfabetica, entao `test_api_*` vem ANTES de `test_fluxo.py`, e o cla da Ana tem contagens
exatas que varios testes de la conferem ("1 de 2", duas linhas de ranking). Escrever missao no cla
da Ana daqui quebraria aquelas contagens sem quebrar nenhuma regra do app, que e o pior tipo de
teste vermelho: o que acusa o lugar errado.

O cla e criado pela propria API, e nao escrevendo no banco. Assim as duas portas de entrada (criar
cla e entrar por convite) sao exercitadas de graca, e a montagem falha alto se elas quebrarem, em
vez de a suite passar verde em cima de um cenario montado por baixo.

Tudo e apagado na saida do modulo, na ordem das FKs. O banco e compartilhado com o resto da suite.
"""

from __future__ import annotations

from datetime import date

import pytest

NOME_DO_CLA = "Cla da API"
MISSAO = "Resumo do Curso da API"
COBRADA = "Missao vqz7 que cobra entrega"
ROTULO = "Link do resumo ou o resumo escrito aqui"

# Um mes fixo, e nao o mes de hoje: o calendario e a unica tela cujo conteudo depende da data em
# que a suite roda, e um teste que so passa em setembro e um teste com prazo de validade.
ANO, MES = 2026, 9
VENCIMENTO = "2026-09-30"


# ----------------------------------------------------------------------------------------------
# Montagem
# ----------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cla_api(cliente_de_api, ana, bruno):  # noqa: ARG001
    """Um cla inteiro criado pela API, com duas pessoas, apagado na saida.

    Depende de `ana` e `bruno` pelo mesmo motivo que `test_isolamento.cla_vizinho`: o Bruno entra
    por um convite que a Ana gera, e as duas contas precisam existir antes de qualquer outro cla
    aparecer no banco. Pedir as fixtures aqui e o que garante essa ordem, em vez de depender de
    qual arquivo o pytest resolveu carregar primeiro.
    """
    from sqlalchemy import delete

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

    nina = cliente_de_api()
    criacao = nina.post(
        "/api/v1/clas",
        json={
            "nome": NOME_DO_CLA,
            "conta": {
                "nome": "Nina Tester",
                "email": "nina@cla.com",
                "telefone": "11933330001",
                "senha": "senhaforte1",
            },
        },
    )
    assert criacao.status_code == 201, criacao.text

    convite = nina.post("/api/v1/convites", json={"dias": 7})
    assert convite.status_code == 201, convite.text

    otto = cliente_de_api()
    entrada = otto.post(
        f"/api/v1/convite/{convite.json()['token']}",
        json={
            "conta": {
                "nome": "Otto Tester",
                "email": "otto@cla.com",
                "telefone": "11933330002",
                "senha": "senhaforte1",
            }
        },
    )
    assert entrada.status_code == 200, entrada.text

    dados = {
        "nina": nina,
        "otto": otto,
        "criacao": criacao.json(),
        "convite": convite.json(),
        "entrada": entrada.json(),
        "cla_id": criacao.json()["cla"]["id"],
        "nina_id": criacao.json()["membro"]["id"],
        "otto_id": entrada.json()["membro"]["id"],
    }
    try:
        yield dados
    finally:
        # De dentro para fora, como manda a FK composta: entrega aponta para membro, membro aponta
        # para cla. Com PRAGMA foreign_keys=ON, inverter a ordem estoura no DELETE.
        db = SessionLocal()
        contas = [criacao.json()["usuario"]["id"], entrada.json()["usuario"]["id"]]
        for modelo in (Log, Entrega, TarefaPessoal, Coluna, Convite, Missao, Membro):
            db.execute(delete(modelo).where(modelo.cla_id == dados["cla_id"]))
        db.execute(delete(Cla).where(Cla.id == dados["cla_id"]))
        db.execute(delete(Usuario).where(Usuario.id.in_(contas)))
        db.commit()
        db.close()


@pytest.fixture(scope="module")
def nina(cla_api):
    return cla_api["nina"]


@pytest.fixture(scope="module")
def otto(cla_api):
    return cla_api["otto"]


@pytest.fixture(scope="module")
def mundo_api():
    """Ids que um passo cria e o seguinte usa. O mesmo papel da fixture `mundo` do fluxo em HTML."""
    return {}


# ----------------------------------------------------------------------------------------------
# Leitores
# ----------------------------------------------------------------------------------------------


def ler(cliente, url: str) -> dict:
    """GET que confere o status ANTES de olhar o corpo.

    Sem isso, uma resposta 401 vira `KeyError: 'missoes'` tres linhas adiante, e a falha acusa a
    chave que faltou em vez de dizer que a sessao morreu. Chave ausente e sintoma; quem explica e o
    status, e ele so aparece se alguem olhar.
    """
    resposta = cliente.get(url)
    assert resposta.status_code == 200, f"GET {url} deu {resposta.status_code}: {resposta.text}"
    return resposta.json()


def pontos_do_cla(cliente) -> int:
    return ler(cliente, "/api/v1/painel")["numeros"]["pontos_gerados"]


def quadro_de(cliente) -> dict:
    return ler(cliente, "/api/v1/quadro")


def chaves_dos_grupos(cliente) -> list[str]:
    return [g["chave"] for g in quadro_de(cliente)["grupos"]]


def grupo(cliente, chave: str) -> dict:
    achado = [g for g in quadro_de(cliente)["grupos"] if g["chave"] == chave]
    assert achado, f"o quadro nao tem o grupo {chave}"
    return achado[0]


def cartao_de(cliente, missao_id: int) -> dict:
    """A linha da missao dentro de `GET /missoes`, com progresso e a entrega de quem pediu."""
    lista = ler(cliente, "/api/v1/missoes")["missoes"]
    achado = [linha for linha in lista if linha["missao"]["id"] == missao_id]
    assert achado, f"a missao {missao_id} nao esta na lista"
    return achado[0]


def linha_do_ranking(cliente, nome: str) -> dict:
    linhas = ler(cliente, "/api/v1/painel")["ranking"]
    achado = [linha for linha in linhas if linha["membro"]["nome"] == nome]
    assert achado, f"{nome} nao aparece no ranking"
    return achado[0]


# ----------------------------------------------------------------------------------------------
# As duas portas de entrada
# ----------------------------------------------------------------------------------------------


def test_criar_cla_pela_api_devolve_a_sessao_inteira(cla_api):
    """Quem abre um cla vira o primeiro membro dele, e ja sai logado.

    A resposta traz conta, participacao, cla e a lista de clas de uma vez porque quem acabou de
    criar mudou as quatro coisas no mesmo movimento.
    """
    estado = cla_api["criacao"]
    assert estado["cla"]["nome"] == NOME_DO_CLA
    assert estado["usuario"]["email"] == "nina@cla.com"
    assert estado["membro"]["nome"] == "Nina Tester"
    assert [c["id"] for c in estado["clas"]] == [cla_api["cla_id"]]


def test_entrar_por_convite_pela_api_poe_a_pessoa_no_cla(cla_api):
    estado = cla_api["entrada"]
    assert estado["cla"]["id"] == cla_api["cla_id"]
    assert estado["membro"]["nome"] == "Otto Tester"
    assert [c["id"] for c in estado["clas"]] == [cla_api["cla_id"]]
    assert cla_api["convite"]["link"].endswith(cla_api["convite"]["token"])


def test_a_lista_de_membros_nao_entrega_email_de_ninguem(nina, cla_api):
    """Regra 2 de `app/api/saida.py`: email so aparece na conta de quem pediu.

    Uma lista de membros com email dentro seria um jeito de qualquer pessoa do cla baixar o email
    de todo mundo, e nenhuma tela precisa disso.
    """
    corpo = ler(nina, "/api/v1/membros")
    assert corpo["total"] == 2
    assert sorted(m["nome"] for m in corpo["membros"]) == ["Nina Tester", "Otto Tester"]
    assert all("email" not in m for m in corpo["membros"])
    assert "otto@cla.com" not in nina.get("/api/v1/membros").text
    assert cla_api["cla_id"] > 0


def test_a_lista_de_membros_tambem_nao_entrega_telefone_de_ninguem(nina):
    """A mesma regra 2, agora com o dado que entrou depois dela.

    O telefone e mais sensivel que o email: com ele se chega na pessoa por fora do app. A assercao
    procura o NUMERO no corpo inteiro, e nao so a chave `telefone` nos membros, porque o vazamento
    nao precisa vir com o nome certo para ser vazamento: bastaria ele aparecer pendurado em
    qualquer outro campo.
    """
    assert "11933330002" not in nina.get("/api/v1/membros").text, (
        "a lista de membros entregou o telefone do Otto"
    )


def test_a_conta_devolve_o_proprio_telefone_e_so_o_proprio(nina, otto):
    """A outra metade da regra: dado pessoal nao some do app, ele fica so com o dono.

    Sem isso, uma tela de editar conta nao teria como mostrar o que a pessoa cadastrou, e o campo
    viraria um lugar onde se escreve e nunca se le. As duas sessoes sao conferidas de proposito: a
    prova de que "so o proprio" e uma regra, e nao a consequencia de so existir uma pessoa.
    """
    assert ler(nina, "/api/v1/sessao")["usuario"]["telefone"] == "11933330001"
    assert ler(otto, "/api/v1/sessao")["usuario"]["telefone"] == "11933330002"
    assert "11933330001" not in otto.get("/api/v1/sessao").text, (
        "a sessao do Otto veio com o telefone da Nina"
    )


def test_a_api_recusa_telefone_invalido_com_a_mesma_regra_da_tela(cliente_de_api):
    """A gemea de `test_conta.py::test_telefone_invalido_...`, e ela existe por um motivo pratico.

    Sao duas portas para o mesmo ato, e a validacao mora em `servicos/contas.py` justamente para
    nao serem duas regras. Uma API que aceitasse o que a tela recusa seria a forma mais silenciosa
    de o banco encher de telefone torto: ninguem olha o que entrou pela porta que nao tem tela.

    Nada e apagado na saida porque nada e criado: 400 nao grava conta nem cla.
    """
    recusa = cliente_de_api().post(
        "/api/v1/clas",
        json={
            "nome": "Cla do Telefone Torto pela API",
            "conta": {
                "nome": "Torto API",
                "email": "torto-api@cla.com",
                "telefone": "9760-1227",
                "senha": "senhaforte1",
            },
        },
    )
    assert recusa.status_code == 400, recusa.text
    assert "Telefone inválido" in recusa.json()["detail"]
    assert "9760" not in recusa.json()["detail"], "a recusa da API repetiu o telefone digitado"


# ----------------------------------------------------------------------------------------------
# Missao, entrega e pontos
# ----------------------------------------------------------------------------------------------


def test_qualquer_membro_sobe_missao(nina, mundo_api):
    resposta = nina.post(
        "/api/v1/missoes",
        json={
            "titulo": MISSAO,
            "descricao": "Entregar resumo escrito",
            "pontos": 500,
            "vencimento": VENCIMENTO,
        },
    )
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["titulo"] == MISSAO and corpo["vencimento"] == VENCIMENTO
    assert corpo["ativa"] is True and corpo["excluida_em"] is None
    mundo_api["missao"] = corpo["id"]


def test_missao_aparece_para_os_outros_membros(otto, mundo_api):
    """A lista ja traz o progresso e a MINHA entrega, para a tela nao pedir uma coisa por missao."""
    linha = cartao_de(otto, mundo_api["missao"])
    assert linha["missao"]["titulo"] == MISSAO
    assert linha["progresso"] == {"feitas": 0, "total": 2, "percentual": 0}
    # `None` e um estado: "ainda nao olhei" nao e a mesma coisa que "olhei e deixei em a fazer".
    assert linha["minha_entrega"] is None


def test_missao_sem_exigencia_conclui_sem_nada_anexado(nina, otto, mundo_api):
    resposta = otto.put(
        f"/api/v1/missoes/{mundo_api['missao']}/entrega",
        json={"status": "concluido", "resposta": "", "observacao": "sem link mesmo"},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["status"] == "concluido"
    assert pontos_do_cla(nina) == 500


def test_missao_pode_exigir_resposta(nina, mundo_api):
    resposta = nina.post(
        "/api/v1/missoes",
        json={
            "titulo": COBRADA,
            "descricao": "Precisa do link",
            "pontos": 100,
            "exige_resposta": True,
            "rotulo_resposta": ROTULO,
        },
    )
    assert resposta.status_code == 201, resposta.text
    mundo_api["cobrada"] = resposta.json()["id"]
    detalhe = nina.get(f"/api/v1/missoes/{mundo_api['cobrada']}").json()
    assert detalhe["rotulo_resposta"] == ROTULO


def test_rotulo_padrao_sai_resolvido_do_servidor(nina, mundo_api):
    """Missao que exige resposta sem escolher rotulo recebe o texto padrao aqui, nao no React.

    O default e regra da missao, e repeti-lo na tela seria uma segunda copia de "Link ou texto da
    entrega" para desandar. Esta missao e criada e excluida no mesmo teste, para nao mudar as
    contagens dos proximos.
    """
    criada = nina.post(
        "/api/v1/missoes", json={"titulo": "Missao vqz7 sem rotulo", "exige_resposta": True}
    ).json()
    detalhe = nina.get(f"/api/v1/missoes/{criada['id']}").json()
    assert detalhe["missao"]["rotulo_resposta"] == ""
    assert detalhe["rotulo_resposta"].strip() != ""
    nina.delete(f"/api/v1/missoes/{criada['id']}")
    assert mundo_api["cobrada"] != criada["id"]


def test_concluir_sem_a_resposta_exigida_da_409_e_nao_grava(nina, otto, mundo_api):
    """409 e nao 400: o pedido esta correto, o que falta e um passo anterior.

    A ultima assercao e a que nao tem gemea em HTML e por isso vale mais: o servico escreve na
    entrega ANTES de descobrir que o campo estava vazio, e sem o rollback da rota a resposta em
    branco ficaria gravada junto com o status antigo.
    """
    resposta = otto.put(
        f"/api/v1/missoes/{mundo_api['cobrada']}/entrega",
        json={"status": "concluido", "resposta": "   ", "observacao": ""},
    )
    assert resposta.status_code == 409, resposta.text
    detalhe = resposta.json()["detail"]
    assert detalhe["codigo"] == "falta_resposta"
    assert "Link do resumo" in detalhe["mensagem"]
    assert detalhe["missao_id"] == mundo_api["cobrada"]
    assert detalhe["rotulo_resposta"] == ROTULO

    assert pontos_do_cla(nina) == 500
    assert cartao_de(otto, mundo_api["cobrada"])["minha_entrega"] is None


def test_arrastar_para_concluido_sem_resposta_e_recusado(otto, mundo_api):
    """O contrato do arrastar e o mesmo do HTML, byte por byte: `ok`, `mensagem` e `url`.

    `app/static/kanban.js` fala esse formato desde antes de existir API, e durante as fases 5 e 6
    as duas interfaces vao arrastar cartao ao mesmo tempo. Um contrato so e o que impede que
    "mover" queira dizer duas coisas diferentes dependendo de quem pediu.
    """
    resposta = otto.post(
        "/api/v1/quadro/mover",
        json={"destino": "concluido", "itens": [f"missao-{mundo_api['cobrada']}"]},
    )
    assert resposta.status_code == 409
    corpo = resposta.json()
    assert set(corpo) == {"ok", "mensagem", "url"}
    assert corpo["ok"] is False
    assert "Link do resumo" in corpo["mensagem"]
    assert corpo["url"] == f"/missoes/{mundo_api['cobrada']}?erro=resposta"


def test_com_a_resposta_preenchida_a_missao_pontua(nina, otto, mundo_api):
    otto.put(
        f"/api/v1/missoes/{mundo_api['cobrada']}/entrega",
        json={"status": "concluido", "resposta": "https://docs.google.com/vqz7", "observacao": ""},
    )
    assert pontos_do_cla(nina) == 600
    detalhe = otto.get(f"/api/v1/missoes/{mundo_api['cobrada']}").json()
    assert detalhe["minha_entrega"]["resposta"] == "https://docs.google.com/vqz7"


def test_detalhe_traz_as_entregas_de_todo_mundo_sem_email(nina, mundo_api):
    """A tela de uma missao mostra quem ja fez. O nome vai junto; o email, nao."""
    detalhe = nina.get(f"/api/v1/missoes/{mundo_api['cobrada']}").json()
    entregas = detalhe["entregas"]
    assert [e["membro"]["nome"] for e in entregas] == ["Otto Tester"]
    assert all("email" not in e["membro"] for e in entregas)
    assert detalhe["progresso"] == {"feitas": 1, "total": 2, "percentual": 50}
    # Quem pediu ainda nao entregou, e isso e diferente de nao existir entrega nenhuma na missao.
    assert detalhe["minha_entrega"] is None


def test_limpar_a_missao_cobrada(nina, mundo_api):
    """Tira a missao de 100 pontos de cena para os testes seguintes contarem so a de 500."""
    resposta = nina.delete(f"/api/v1/missoes/{mundo_api['cobrada']}")
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    # DELETE, mas a linha fica: o verbo diz o que o pedido quer, nao o que o app faz com ele.
    assert corpo["ativa"] is False and corpo["excluida_em"] is not None
    ids = [linha["missao"]["id"] for linha in ler(nina, "/api/v1/missoes")["missoes"]]
    assert mundo_api["cobrada"] not in ids
    assert pontos_do_cla(nina) == 500


# ----------------------------------------------------------------------------------------------
# Quadro e calendario
# ----------------------------------------------------------------------------------------------


def test_quadro_comeca_nas_tres_etapas_padrao(nina):
    assert chaves_dos_grupos(nina) == ["a_fazer", "fazendo", "concluido"]


def test_calendario_traz_o_vencimento_no_dia_certo(nina):
    """A grade vem montada do servidor: semana comecando no domingo, com os dias vizinhos dentro.

    Remontar isso no navegador seria reescrever o modulo `calendar` do Python em TypeScript para
    chegar na mesma tabela. O ano e o mes vao explicitos no pedido para o teste nao depender de em
    que mes a suite esta rodando.
    """
    corpo = nina.get(f"/api/v1/calendario?ano={ANO}&mes={MES}").json()
    assert (corpo["ano"], corpo["mes"], corpo["mes_nome"]) == (ANO, MES, "Setembro")
    assert corpo["mes_anterior"] == [2026, 8] and corpo["mes_seguinte"] == [2026, 10]
    assert all(len(semana) == 7 for semana in corpo["semanas"])

    dias = [dia for semana in corpo["semanas"] for dia in semana]
    vencimento = [dia for dia in dias if dia["data"] == VENCIMENTO]
    assert len(vencimento) == 1
    assert [e["titulo"] for e in vencimento[0]["eventos"]] == [MISSAO]
    assert vencimento[0]["do_mes"] is True


def test_mes_fora_da_faixa_volta_para_hoje(nina):
    """A tela navega somando e subtraindo um: e mais util voltar para hoje do que dar erro."""
    corpo = ler(nina, "/api/v1/calendario?ano=2026&mes=13")
    hoje = date.today()
    assert (corpo["ano"], corpo["mes"]) == (hoje.year, hoje.month)


# ----------------------------------------------------------------------------------------------
# Tarefa pessoal
# ----------------------------------------------------------------------------------------------


def test_tarefa_pessoal_aparece_na_lista(nina, mundo_api):
    resposta = nina.post(
        "/api/v1/tarefas", json={"titulo": "Tarefa privada vqz7 da Nina", "prazo": "2026-09-25"}
    )
    assert resposta.status_code == 201, resposta.text
    mundo_api["tarefa_nina"] = resposta.json()["id"]
    titulos = [t["titulo"] for t in ler(nina, "/api/v1/tarefas")["tarefas"]]
    assert "Tarefa privada vqz7 da Nina" in titulos


def test_tarefa_pessoal_nao_vaza_para_outro_membro(otto):
    assert "vqz7" not in otto.get("/api/v1/tarefas").text


def test_cartao_aberto_troca_titulo_e_prazo(nina, mundo_api):
    resposta = nina.put(
        f"/api/v1/tarefas/{mundo_api['tarefa_nina']}",
        json={"titulo": "Tarefa privada vqz7 renomeada", "prazo": "2026-09-28"},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["titulo"] == "Tarefa privada vqz7 renomeada"
    assert resposta.json()["prazo"] == "2026-09-28"


def test_da_para_tirar_o_prazo_da_tarefa(nina, mundo_api):
    """`null` no prazo e "sem prazo", e nao "nao mexi no prazo"."""
    resposta = nina.put(
        f"/api/v1/tarefas/{mundo_api['tarefa_nina']}",
        json={"titulo": "Tarefa privada vqz7 renomeada", "prazo": None},
    )
    assert resposta.json()["prazo"] is None


def test_data_impossivel_e_recusada_com_422(nina, mundo_api):
    """Aqui a API se afasta da tela de proposito, e e o unico lugar do fluxo onde isso acontece.

    O formulario recebe "30/02/2026" e redireciona sem gravar, porque uma pagina nao pode responder
    ao clique com um erro de tipo no meio do quadro. A API responde 422, que e o que o React precisa
    para marcar o campo em vermelho. O que nao muda e o efeito: nos dois casos nada e gravado.
    """
    resposta = nina.put(
        f"/api/v1/tarefas/{mundo_api['tarefa_nina']}",
        json={"titulo": "Tarefa privada vqz7 renomeada", "prazo": "30/02/2026"},
    )
    assert resposta.status_code == 422
    atual = ler(nina, "/api/v1/tarefas")["tarefas"]
    alvo = [t for t in atual if t["id"] == mundo_api["tarefa_nina"]][0]
    assert alvo["titulo"] == "Tarefa privada vqz7 renomeada" and alvo["prazo"] is None


def test_membro_nao_edita_tarefa_de_outro(otto, mundo_api):
    """404 e nao 403: 403 confirmaria que a tarefa existe, que e meia resposta."""
    resposta = otto.put(f"/api/v1/tarefas/{mundo_api['tarefa_nina']}", json={"titulo": "invadida"})
    assert resposta.status_code == 404


# ----------------------------------------------------------------------------------------------
# Colunas
# ----------------------------------------------------------------------------------------------


def test_membro_cria_coluna_propria(nina, mundo_api):
    from app.servicos.colunas import MAX_COLUNAS

    resposta = nina.post("/api/v1/colunas", json={"nome": "Coluna vqz7 da Nina"})
    assert resposta.status_code == 201, resposta.text
    mundo_api["coluna_nina"] = resposta.json()["id"]

    corpo = ler(nina, "/api/v1/colunas")
    assert [c["nome"] for c in corpo["colunas"]] == ["Coluna vqz7 da Nina"]
    assert corpo["maximo"] == MAX_COLUNAS and corpo["pode_criar"] is True


def test_coluna_de_um_nao_aparece_para_o_outro(otto):
    assert ler(otto, "/api/v1/colunas")["colunas"] == []


def test_membro_nao_move_cartao_para_coluna_alheia(otto, mundo_api):
    resposta = otto.post(
        "/api/v1/quadro/mover",
        json={
            "destino": f"c{mundo_api['coluna_nina']}",
            "itens": [f"missao-{mundo_api['missao']}"],
        },
    )
    assert resposta.status_code == 400


def test_tirar_do_concluido_zera_os_pontos(nina, otto, mundo_api):
    resposta = otto.post(
        "/api/v1/quadro/mover",
        json={"destino": "fazendo", "itens": [f"missao-{mundo_api['missao']}"]},
    )
    assert resposta.json() == {"ok": True, "pontos": 0}
    assert pontos_do_cla(nina) == 0


def test_voltar_para_concluido_devolve_os_pontos(nina, otto, mundo_api):
    resposta = otto.post(
        "/api/v1/quadro/mover",
        json={"destino": "concluido", "itens": [f"missao-{mundo_api['missao']}"]},
    )
    assert resposta.json() == {"ok": True, "pontos": 500}
    assert pontos_do_cla(nina) == 500


def test_cartao_arrastado_fica_na_coluna_criada(nina, mundo_api):
    criada = nina.post("/api/v1/tarefas", json={"titulo": "Tarefa vqz7 na coluna nova"}).json()
    mundo_api["tarefa_na_coluna"] = criada["id"]
    nina.post(
        "/api/v1/quadro/mover",
        json={"destino": f"c{mundo_api['coluna_nina']}", "itens": [f"pessoal-{criada['id']}"]},
    )
    dentro = grupo(nina, f"c{mundo_api['coluna_nina']}")["itens"]
    assert [i["chave"] for i in dentro] == [f"pessoal-{criada['id']}"]


def test_tarefa_criada_com_destino_nasce_na_coluna(nina, mundo_api):
    """`destino` e vocabulario do quadro: "cN" so quer dizer alguma coisa para quem desenha colunas.

    A rota resolve isso antes de chamar o servico, que recebe coluna_id e status, que e o que a
    tarefa de fato guarda.
    """
    resposta = nina.post(
        "/api/v1/tarefas",
        json={"titulo": "Direto na coluna vqz7", "destino": f"c{mundo_api['coluna_nina']}"},
    )
    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["coluna_id"] == mundo_api["coluna_nina"]
    titulos = [i["titulo"] for i in grupo(nina, f"c{mundo_api['coluna_nina']}")["itens"]]
    assert "Direto na coluna vqz7" in titulos


def test_destino_que_nao_existe_e_recusado(nina):
    resposta = nina.post("/api/v1/tarefas", json={"titulo": "vqz7 no vazio", "destino": "c987654"})
    assert resposta.status_code == 400
    assert "vqz7 no vazio" not in nina.get("/api/v1/tarefas").text


def test_membro_salva_a_ordem_das_colunas(nina, otto, mundo_api):
    ordem = [f"c{mundo_api['coluna_nina']}", "concluido", "a_fazer", "fazendo"]
    mundo_api["ordem"] = ordem
    resposta = nina.put("/api/v1/colunas/ordem", json={"colunas": ordem})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["ordem"] == ",".join(ordem)
    assert chaves_dos_grupos(nina) == ordem
    # A ordem e de quem salvou: o quadro do outro nao se mexe.
    assert chaves_dos_grupos(otto)[0] == "a_fazer"


def test_ordem_sem_todas_as_colunas_e_recusada(nina, mundo_api):
    """Ordem pela metade seria gravada pela metade, e o que faltasse cairia no fim do quadro."""
    resposta = nina.put("/api/v1/colunas/ordem", json={"colunas": ["a_fazer"]})
    assert resposta.status_code == 400
    assert chaves_dos_grupos(nina) == mundo_api["ordem"]


def test_excluir_coluna_e_204_e_devolve_o_cartao(nina, mundo_api):
    """A unica exclusao do app que e DELETE de verdade, e por isso a unica que devolve 204.

    Nao ha o que restaurar: a coluna e um agrupamento sem significado proprio. O que estava dentro
    dela volta para "A fazer" em vez de sumir junto.
    """
    resposta = nina.delete(f"/api/v1/colunas/{mundo_api['coluna_nina']}")
    assert resposta.status_code == 204
    assert resposta.content == b""

    assert ler(nina, "/api/v1/colunas")["colunas"] == []
    assert chaves_dos_grupos(nina) == ["concluido", "a_fazer", "fazendo"]
    a_fazer = [i["chave"] for i in grupo(nina, "a_fazer")["itens"]]
    assert f"pessoal-{mundo_api['tarefa_na_coluna']}" in a_fazer


# ----------------------------------------------------------------------------------------------
# Lixeira e historico
# ----------------------------------------------------------------------------------------------


def test_missao_excluida_some_da_lista_e_vai_para_o_historico(nina, mundo_api):
    nina.delete(f"/api/v1/missoes/{mundo_api['missao']}")
    ativas = [linha["missao"]["id"] for linha in ler(nina, "/api/v1/missoes")["missoes"]]
    assert mundo_api["missao"] not in ativas

    lixeira = ler(nina, "/api/v1/historico")["missoes"]
    alvo = [m for m in lixeira if m["id"] == mundo_api["missao"]]
    assert len(alvo) == 1
    # `excluida_por` so existe nesta tela, e custa uma leitura a mais por missao.
    assert alvo[0]["excluida_por"]["nome"] == "Nina Tester"
    assert "email" not in alvo[0]["excluida_por"]
    assert pontos_do_cla(nina) == 0


def test_missao_restaurada_volta_com_os_pontos(nina, mundo_api):
    resposta = nina.post(f"/api/v1/historico/missoes/{mundo_api['missao']}/restaurar")
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["ativa"] is True
    assert pontos_do_cla(nina) == 500


def test_tarefa_excluida_vai_para_o_historico_e_volta(nina, mundo_api):
    alvo = mundo_api["tarefa_nina"]
    nina.delete(f"/api/v1/tarefas/{alvo}")
    assert alvo not in [t["id"] for t in ler(nina, "/api/v1/tarefas")["tarefas"]]
    assert alvo in [t["id"] for t in ler(nina, "/api/v1/historico")["tarefas"]]

    nina.post(f"/api/v1/historico/tarefas/{alvo}/restaurar")
    assert alvo in [t["id"] for t in ler(nina, "/api/v1/tarefas")["tarefas"]]


def test_o_log_guarda_quem_fez_o_que(nina, mundo_api):
    logs = ler(nina, "/api/v1/historico")["logs"]
    assert logs, "o historico do cla nao registrou nada"
    criou = [
        registro
        for registro in logs
        if registro["acao"] == "criou"
        and registro["entidade"] == "missao"
        and registro["entidade_id"] == mundo_api["missao"]
    ]
    assert criou and criou[0]["membro"]["nome"] == "Nina Tester"
    assert "email" not in criou[0]["membro"]


def test_o_log_do_cla_nao_mostra_tarefa_pessoal(nina, otto, mundo_api):
    """A tarefa vqz7 da Nina foi criada, excluida e restaurada acima: tres registros no log.

    Nenhum pode chegar ao feed, nem para o Otto nem para a propria Nina: o feed e do cla, e o titulo
    de uma tarefa privada ali e o que a regra "tarefa pessoal so o dono ve" existe para impedir.
    Olha a API e a tela, porque as duas leem o log, e o texto inteiro, porque o vazamento e o titulo.
    """
    for quem in (nina, otto):
        logs = ler(quem, "/api/v1/historico")["logs"]
        assert logs, "o feed ficou vazio: o filtro tirou mais do que tarefa pessoal"
        assert not [r for r in logs if r["entidade"] == "tarefa"], "tarefa pessoal no feed do cla"
        # O titulo inteiro, e nao so "vqz7": uma MISSAO deste arquivo tambem tem vqz7 no nome, e ela
        # esta na lixeira, onde deve aparecer.
        assert "Tarefa privada vqz7" not in quem.get("/historico").text, (
            "o titulo da tarefa pessoal vazou na tela"
        )
    assert any(r["entidade"] == "missao" for r in ler(otto, "/api/v1/historico")["logs"])


# ----------------------------------------------------------------------------------------------
# Painel
# ----------------------------------------------------------------------------------------------


def test_painel_fecha_a_conta_consigo_mesmo(nina):
    """As quatro coisas saem de uma leitura so, e por isso elas tem que concordar entre si.

    Somar o ranking e comparar com os numeros nao e redundancia: ja houve uma versao em que o total
    do cla e a soma por pessoa discordavam, e nenhum dos dois numeros parecia errado sozinho.
    """
    corpo = ler(nina, "/api/v1/painel")
    numeros, ranking, grafico = corpo["numeros"], corpo["ranking"], corpo["grafico"]

    assert numeros["total_membros"] == 2 and numeros["total_missoes"] == 1
    assert numeros["pontos_gerados"] == 500
    assert numeros["entregas_concluidas"] == 1 and numeros["entregas_possiveis"] == 2
    assert sum(linha["pontos"] for linha in ranking) == numeros["pontos_gerados"]
    assert sum(barra["quantidade"] for barra in grafico) == numeros["entregas_concluidas"]
    assert len(corpo["missoes"]) == numeros["total_missoes"]


def test_ranking_traz_o_relatorio_dentro_da_propria_linha(nina):
    """O relatorio vai junto porque e ele que abre quando alguem clica na linha.

    Devolver so o total obrigaria a tela a pedir de novo, por pessoa, a mesma conta que acabou de
    ser feita: num cla de 17 pessoas isso e um pedido contra dezessete.
    """
    corpo = ler(nina, "/api/v1/painel")
    assert [linha["membro"]["nome"] for linha in corpo["ranking"]] == [
        "Otto Tester",
        "Nina Tester",
    ]
    assert [linha["posicao"] for linha in corpo["ranking"]] == [1, 2]

    de_otto = linha_do_ranking(nina, "Otto Tester")["relatorio"]
    assert len(de_otto["concluidas"]) == 1 and de_otto["fazendo"] == []
    assert de_otto["concluidas"][0]["missao"]["titulo"] == MISSAO
    assert de_otto["pontos"] == linha_do_ranking(nina, "Otto Tester")["pontos"] == 500

    de_nina = linha_do_ranking(nina, "Nina Tester")["relatorio"]
    assert len(de_nina["a_fazer"]) == 1 and de_nina["pontos"] == 0


def test_grafico_traz_uma_barra_por_missao(nina):
    grafico = ler(nina, "/api/v1/painel")["grafico"]
    assert len(grafico) == 1
    barra = grafico[0]
    assert barra["missao"]["titulo"] == MISSAO
    assert barra["quantidade"] == 1 and barra["percentual"] == 50
    assert [q["nome"] for q in barra["quem"]] == ["Otto Tester"]


def test_tarefa_pessoal_nao_entra_em_relatorio_nenhum(otto, nina):
    """O painel e do cla. Tarefa pessoal e de uma pessoa so, e nao aparece nem para o dono."""
    assert "vqz7" not in otto.get("/api/v1/painel").text
    assert "vqz7" not in nina.get("/api/v1/painel").text


def test_missao_em_coluna_privada_conta_como_nao_comecada(nina, otto, mundo_api):
    """Cartao guardado em gaveta nao pontua, e a gaveta continua invisivel para o resto do cla."""
    coluna = otto.post("/api/v1/colunas", json={"nome": "Gaveta vqz7 do Otto"}).json()
    mundo_api["coluna_otto"] = coluna["id"]
    otto.post(
        "/api/v1/quadro/mover",
        json={"destino": f"c{coluna['id']}", "itens": [f"missao-{mundo_api['missao']}"]},
    )
    assert pontos_do_cla(nina) == 0
    assert len(linha_do_ranking(nina, "Otto Tester")["relatorio"]["a_fazer"]) == 1
    assert "Gaveta vqz7" not in nina.get("/api/v1/painel").text


def test_voltar_da_coluna_privada_devolve_os_pontos(nina, otto, mundo_api):
    otto.post(
        "/api/v1/quadro/mover",
        json={"destino": "concluido", "itens": [f"missao-{mundo_api['missao']}"]},
    )
    assert pontos_do_cla(nina) == 500


def test_membro_nao_exclui_coluna_de_outro(nina, otto, mundo_api):
    """404 e nao 403, pelo mesmo motivo da tarefa: 403 confirmaria que a coluna existe."""
    assert nina.delete(f"/api/v1/colunas/{mundo_api['coluna_otto']}").status_code == 404
    assert [c["nome"] for c in ler(otto, "/api/v1/colunas")["colunas"]] == ["Gaveta vqz7 do Otto"]
