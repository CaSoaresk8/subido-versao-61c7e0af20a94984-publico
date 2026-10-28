"""As duas portas do app (criar um cla, usar um convite) e a troca de cla ativo.

Toda entrada de gente acontece no cla da Carla, nunca no cla da Ana: o cla da Ana precisa ficar com
duas pessoas para as contagens do ranking e do grafico baterem. Ver o conftest.

Quem faz login neste arquivo usa cliente proprio, nunca o `visitante`: login gruda cookie no
cliente, e o `visitante` e de sessao inteira, entao uma sessao deixada nele apareceria como teste
de outro arquivo falhando sozinho.

O que estes testes protegem, em uma frase cada:

- convite e credencial inteira, entao validade, revogacao e limite de usos tem que ser conferidos
  no POST e nao so na tela;
- cla de que a pessoa nao participa da 404, e nao 403, porque 403 confirmaria que o id existe;
- o `proximo` do login so aceita caminho do proprio app, senao a tela de login viraria ponte para
  jogar alguem para fora logo depois de digitar a senha.
"""

from __future__ import annotations

import re


def _cliente(app_web):
    from fastapi.testclient import TestClient

    return TestClient(app_web)


def _entrar_por_convite(app_web, token: str, nome: str, email: str):
    cliente = _cliente(app_web)
    resposta = cliente.post(
        f"/convite/{token}",
        data={
            "nome": nome,
            "email": email,
            "telefone": "11912340000",
            "senha": "senhaforte1",
        },
        follow_redirects=True,
    )
    return cliente, resposta


def _id_do_cla(cliente, nome: str) -> int:
    """O cla_id que o seletor do cabecalho usa, lido da tela de quem participa dele.

    Sai do HTML e nao do banco porque e esse o numero que o navegador manda no POST: se a tela
    escrever outro, o teste tem que falhar junto.
    """
    pagina = cliente.get("/").text
    for bloco in re.findall(r'<form method="post" action="/cla/ativo">.*?</form>', pagina, re.S):
        if nome in bloco:
            achado = re.search(r'name="cla_id" value="(\d+)"', bloco)
            assert achado is not None
            return int(achado.group(1))
    raise AssertionError(f"o seletor nao ofereceu o cla {nome!r}")


# ---------- a tela do convite ----------


def test_convite_valido_mostra_o_nome_do_cla(carla, visitante, gerar_convite):
    _, token = gerar_convite(carla, dias=7, max_usos="")
    resposta = visitante.get(f"/convite/{token}")
    assert resposta.status_code == 200
    # Quem tem token valido na mao ja foi autorizado a entrar, e precisa saber onde esta entrando.
    assert "Cla da Carla" in resposta.text


def test_convite_mostra_o_cla_do_token_e_nao_o_cla_ativo(ana, carla, gerar_convite):
    """Quem ja esta logado em um cla e convidado para outro tem que ler o nome do cla do TOKEN.

    A tela do convite e uma das poucas do app em que o cla em destaque nao e o cla ativo da sessao,
    e as duas coisas chegavam no template com o mesmo nome (`cla`). Como o context processor roda
    depois do contexto da rota, o cla ativo ganhava: a Ana veria o convite da Carla com o nome do
    proprio cla no titulo, e aceitaria achando que era outra coisa.

    So GET, de proposito: a Ana e cliente de sessao inteira e este teste nao pode mexer no cla dela.
    """
    _, token = gerar_convite(carla, dias=7, max_usos="")
    pagina = ana.get(f"/convite/{token}").text
    assert '<div class="marca">Cla da Carla</div>' in pagina
    assert '<div class="marca">Cla de Teste</div>' not in pagina


def test_convite_inexistente_da_404_e_nao_conta_nome_de_cla(visitante):
    resposta = visitante.get("/convite/token-que-nunca-existiu")
    assert resposta.status_code == 404
    assert "Cla da Carla" not in resposta.text
    assert "Cla de Teste" not in resposta.text


def test_convite_revogado_para_de_valer(app_web, carla, visitante, gerar_convite):
    convite_id, token = gerar_convite(carla, dias=7, max_usos="")
    assert visitante.get(f"/convite/{token}").status_code == 200

    carla.post(f"/cla/convites/{convite_id}/revogar", follow_redirects=True)
    recusado = visitante.get(f"/convite/{token}")
    assert recusado.status_code == 400
    assert "revogado" in recusado.text
    # E o POST tambem recusa, nao so o GET: entre abrir a pagina e clicar no botao o convite pode
    # ter sido revogado por outra pessoa, e conferir so na tela deixaria a recusa valendo enquanto
    # a aba estivesse aberta.
    tentativa = _cliente(app_web).post(
        f"/convite/{token}",
        data={
            "nome": "Nao Entra",
            "email": "naoentra@cla.com",
            "telefone": "11912340001",
            "senha": "senhaforte1",
        },
    )
    assert tentativa.status_code == 400


def test_revogar_convite_de_outro_cla_da_404(ana, carla, gerar_convite):
    convite_id, _ = gerar_convite(carla, dias=7, max_usos="")
    # A Ana e membro de um cla, mas nao deste convite. 403 aqui confirmaria que o id existe.
    assert ana.post(f"/cla/convites/{convite_id}/revogar").status_code == 404


def test_convite_com_validade_fora_da_lista_e_recusado(carla):
    resposta = carla.post("/cla/convites", data={"dias": 999999}, follow_redirects=False)
    assert resposta.status_code == 303
    # Sem o teto, dias=999999 geraria um convite que na pratica nunca vence.
    assert "erro=" in resposta.headers["location"]


# ---------- entrar por convite ----------


def test_entra_por_convite_e_cai_dentro_do_cla(app_web, carla, gerar_convite):
    _, token = gerar_convite(carla, dias=7, max_usos="")
    cliente, resposta = _entrar_por_convite(app_web, token, "Davi Tester", "davi@cla.com")
    assert "Dashboard do clã" in resposta.text
    # O cabecalho do cla novo e a prova de que a sessao abriu no cla do token, e nao em outro.
    assert "Cla da Carla" in cliente.get("/").text


def test_convite_esgota_no_limite_de_usos(app_web, carla, gerar_convite):
    _, token = gerar_convite(carla, dias=7, max_usos=1)
    _, primeira = _entrar_por_convite(app_web, token, "Elisa Tester", "elisa@cla.com")
    assert "Dashboard do clã" in primeira.text

    segunda = _cliente(app_web).post(
        f"/convite/{token}",
        data={
            "nome": "Fabio Tester",
            "email": "fabio@cla.com",
            "telefone": "11912340002",
            "senha": "senhaforte1",
        },
    )
    assert segunda.status_code == 400
    assert "limite de usos" in segunda.text


def test_quem_ja_e_membro_nao_gasta_uso_do_convite(app_web, carla, gerar_convite):
    """Link reaberto por quem ja esta dentro nao e entrada nova.

    Sem isso, alguem que ja e membro abrindo o proprio link de convite esgotaria o convite dos
    outros sem ninguem ter entrado.
    """
    _, token = gerar_convite(carla, dias=7, max_usos=1)
    # A propria Carla e membro: o POST dela nao pode consumir o uso.
    assert carla.post(f"/convite/{token}", follow_redirects=True).status_code == 200

    cliente, resposta = _entrar_por_convite(app_web, token, "Gabi Tester", "gabi@cla.com")
    assert "Dashboard do clã" in resposta.text, "o uso foi gasto por quem ja era membro"
    assert "Cla da Carla" in cliente.get("/").text


# ---------- cla ativo ----------


def test_seletor_aparece_so_com_mais_de_um_cla(app_web, carla, gerar_convite):
    # Com um cla so, o nome no topo nao e um menu: nao ha para onde trocar.
    assert "seletor-cla" not in carla.get("/").text

    _, token = gerar_convite(carla, dias=7, max_usos="")
    cliente, _ = _entrar_por_convite(app_web, token, "Hugo Tester", "hugo@cla.com")
    cliente.post(
        "/criar-cla",
        data={"nome_cla": "Cla do Hugo", "nome": "", "email": "", "senha": ""},
        follow_redirects=True,
    )
    pagina = cliente.get("/").text
    assert "seletor-cla" in pagina
    assert "Cla da Carla" in pagina
    assert "Cla do Hugo" in pagina


def test_troca_de_cla_ativo_e_o_antigo_continua_editavel(app_web, carla, gerar_convite):
    _, token = gerar_convite(carla, dias=7, max_usos="")
    cliente, _ = _entrar_por_convite(app_web, token, "Ivo Tester", "ivo@cla.com")
    cliente.post(
        "/criar-cla",
        data={"nome_cla": "Cla do Ivo", "nome": "", "email": "", "senha": ""},
        follow_redirects=True,
    )
    assert "Cla do Ivo" in cliente.get("/").text

    cliente.post(
        "/cla/ativo", data={"cla_id": _id_do_cla(cliente, "Cla da Carla")}, follow_redirects=True
    )
    # Voltou para o cla anterior, que continua existindo e editavel: nada congela na troca.
    assert "Cla da Carla" in cliente.get("/").text
    assert cliente.get("/missoes/nova").status_code == 200


def test_trocar_para_cla_de_que_nao_participa_da_404(ana, carla):
    """O POST de troca reconfere a participacao no banco antes de mexer na sessao.

    Sem isso, escrever um cla_id na mao seria o jeito de entrar em qualquer cla, e o cookie
    passaria a valer como autorizacao.
    """
    # O id sai do banco, e nao da tela: a tela da Ana nao oferece o cla da Carla em lugar nenhum,
    # que e justamente o ponto. Aqui o teste esta montando um pedido que so um atacante faria.
    from app.database import SessionLocal
    from app.repositorios import contas as repo_contas

    db = SessionLocal()
    try:
        dona = repo_contas.usuario_por_email(db, "carla@cla.com")
        assert dona is not None, "a fixture carla nao criou a conta"
        participacoes = repo_contas.membros_do_usuario(db, dona.id)
        assert participacoes, "a conta da Carla nao esta em cla nenhum"
        cla_da_carla = participacoes[0].cla_id
    finally:
        db.close()

    # A Ana esta logada, entao nao e falta de sessao: e cla que nao e dela. 404 e nao 403.
    assert ana.post("/cla/ativo", data={"cla_id": cla_da_carla}).status_code == 404


# ---------- destino depois do login ----------


def test_login_volta_para_o_convite_que_pediu(app_web, carla, gerar_convite):
    """Quem JA tem conta precisa conseguir aceitar um convite, e por isso o login aceita `proximo`.

    E o caso das pessoas que ja estao no app e vao ser chamadas para um segundo cla: sem isso elas
    cairiam no cla antigo e o convite ficaria sem uso.
    """
    _, token = gerar_convite(carla, dias=7, max_usos="")
    cliente = _cliente(app_web)
    pagina = cliente.get(f"/login?proximo=/convite/{token}")
    assert f'name="proximo" value="/convite/{token}"' in pagina.text

    resposta = cliente.post(
        "/login",
        data={"email": "carla@cla.com", "senha": "senhaforte1", "proximo": f"/convite/{token}"},
        follow_redirects=False,
    )
    assert resposta.headers["location"] == f"/convite/{token}"


def test_proximo_para_fora_do_app_e_recusado(app_web, visitante):
    # `//outro.site` e endereco absoluto para o navegador. Aceitar isso faria da tela de login uma
    # ponte para jogar alguem para fora logo depois de ter digitado a senha aqui.
    assert 'name="proximo" value="/"' in visitante.get("/login?proximo=//outro.site").text
    resposta = _cliente(app_web).post(
        "/login",
        data={"email": "ana@cla.com", "senha": "senhaforte1", "proximo": "//outro.site"},
        follow_redirects=False,
    )
    assert resposta.headers["location"] == "/"


# ---------- logo do cla ----------


def _icone_do_app() -> str:
    """O endereco do icone do app, que e o simbolo de quem ainda nao subiu logo.

    Sai versionado (`?v=`) pelo mesmo motivo do favicon: e o mesmo arquivo, e sem o numero no
    endereco o cabecalho continuaria mostrando a arte antiga que o navegador ja tem guardada.

    O numero e o mtime do PNG, entao ele muda de maquina para maquina e nao pode ser escrito aqui
    na mao. O import fica dentro da funcao, e nao no topo do arquivo, pelo motivo escrito no
    conftest: nada de `app.*` antes das variaveis de ambiente valerem.
    """
    from app.config import VERSAO_ICONE

    return f"/static/icone-192.png?v={VERSAO_ICONE}"


def _png(cor=(200, 30, 30), lado: int = 8) -> bytes:
    """Um PNG de verdade, montado na hora. Nenhum arquivo de fixture no disco para ficar velho."""
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (lado, lado), cor).save(buffer, format="PNG")
    return buffer.getvalue()


def _src_do_simbolo(cliente) -> str:
    """O endereco que o cabecalho esta usando para a imagem do cla ativo."""
    achado = re.search(r'<img class="simbolo-topo"[^>]*src="([^"]+)"', cliente.get("/").text)
    assert achado is not None, "o cabecalho nao desenhou o simbolo do cla"
    return achado.group(1)


def _sem_logo(cliente) -> None:
    """Devolve o cla ao estado sem logo. Teste que deixa logo para tras mente no teste seguinte."""
    cliente.post("/cla/logo", data={"remover": "1"}, follow_redirects=False)


def test_cla_sem_logo_usa_o_icone_do_app(carla):
    # O espaco do simbolo ja esta reservado no layout: sem logo ele cai no icone, e nao fica vazio.
    assert _src_do_simbolo(carla) == _icone_do_app()


def test_logo_enviado_aparece_no_topo_e_e_servido(carla):
    try:
        envio = carla.post(
            "/cla/logo",
            files={"logo": ("marca.png", _png(), "image/png")},
            follow_redirects=False,
        )
        assert envio.status_code == 303

        src = _src_do_simbolo(carla)
        assert src.startswith("/logos/cla-") and src.endswith(".png")
        arquivo = carla.get(src)
        # O que sai de /logos/ e sempre PNG, mesmo que tenha entrado JPG: o app regrava a imagem.
        assert arquivo.status_code == 200
        assert arquivo.content[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        _sem_logo(carla)


def test_jpg_entra_e_sai_como_png(carla):
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), (10, 90, 200)).save(buffer, format="JPEG")
    try:
        carla.post("/cla/logo", files={"logo": ("foto.jpg", buffer.getvalue(), "image/jpeg")})
        assert carla.get(_src_do_simbolo(carla)).content[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        _sem_logo(carla)


def test_arquivo_que_nao_e_imagem_e_recusado(carla):
    """SVG com script dentro seria XSS na origem do app, com o cookie de quem esta olhando.

    O nome e o content-type do upload dizem "imagem"; os dois vem de quem mandou o pedido e nao
    valem nada. Quem recusa e a decodificacao: o Pillow nao abre isso, entao nao ha o que gravar.
    """
    veneno = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    try:
        carla.post("/cla/logo", files={"logo": ("logo.png", veneno, "image/png")})
        assert _src_do_simbolo(carla) == _icone_do_app(), "o arquivo recusado virou logo"
    finally:
        _sem_logo(carla)


def test_imagem_de_formato_fora_da_lista_e_recusada(carla):
    """GIF abre sem erro nenhum no Pillow, e mesmo assim nao vira logo.

    Este e um caso diferente do SVG: la a decodificacao ja falhava sozinha, entao a lista de
    formatos nunca era consultada. Aqui a imagem e legitima e o UNICO motivo da recusa e
    `imagem.format not in FORMATOS`. Sem este teste, apagar aquela linha nao quebrava nada, e o
    formulario passaria a aceitar em silencio um formato que ele mesmo diz nao aceitar (GIF anima,
    e o primeiro quadro virando PNG estatico nao e o que a pessoa mandou).
    """
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), (0, 200, 90)).save(buffer, format="GIF")
    try:
        carla.post("/cla/logo", files={"logo": ("anima.gif", buffer.getvalue(), "image/gif")})
        assert _src_do_simbolo(carla) == _icone_do_app(), (
            "GIF virou logo apesar de estar fora da lista"
        )
    finally:
        _sem_logo(carla)


def test_arquivo_grande_demais_e_recusado(carla):
    from app.servicos.logos import MAXIMO_BYTES

    try:
        # Precisa ser grande DE VERDADE, e nao um PNG minusculo com o content-length mentindo: o
        # teto e medido sobre os bytes que chegaram.
        carla.post(
            "/cla/logo", files={"logo": ("gordo.png", b"\x89PNG" * MAXIMO_BYTES, "image/png")}
        )
        assert _src_do_simbolo(carla) == _icone_do_app()
    finally:
        _sem_logo(carla)


def test_trocar_o_logo_apaga_o_arquivo_anterior(carla):
    try:
        carla.post("/cla/logo", files={"logo": ("um.png", _png((10, 10, 10)), "image/png")})
        antigo = _src_do_simbolo(carla)
        carla.post("/cla/logo", files={"logo": ("dois.png", _png((250, 250, 0)), "image/png")})
        novo = _src_do_simbolo(carla)

        # Endereco novo a cada troca: o nome carrega um sufixo aleatorio justamente para o cache do
        # navegador e do service worker nao continuarem servindo o logo antigo.
        assert novo != antigo
        assert carla.get(novo).status_code == 200
        # E o arquivo antigo sai do volume, senao cada troca deixaria lixo para sempre.
        assert carla.get(antigo).status_code == 404
    finally:
        _sem_logo(carla)


def test_tirar_o_logo_volta_para_o_icone_do_app(carla):
    carla.post("/cla/logo", files={"logo": ("um.png", _png(), "image/png")})
    assert _src_do_simbolo(carla) != _icone_do_app()
    carla.post("/cla/logo", data={"remover": "1"})
    assert _src_do_simbolo(carla) == _icone_do_app()


def test_logo_de_um_cla_nao_aparece_no_outro(ana, carla):
    try:
        carla.post("/cla/logo", files={"logo": ("um.png", _png(), "image/png")})
        assert _src_do_simbolo(carla).startswith("/logos/")
        # O logo e do cla, nao do app: quem esta noutro cla continua vendo o icone.
        assert _src_do_simbolo(ana) == _icone_do_app()
    finally:
        _sem_logo(carla)


def test_cla_pode_nascer_ja_com_logo(app_web):
    cliente = _cliente(app_web)
    resposta = cliente.post(
        "/criar-cla",
        data={
            "nome_cla": "Cla do Logo",
            "nome": "Joana Tester",
            "email": "joana@cla.com",
            "telefone": "11912340003",
            "senha": "senhaforte1",
        },
        files={"logo": ("marca.png", _png((0, 120, 255)), "image/png")},
        follow_redirects=True,
    )
    assert "Dashboard do clã" in resposta.text
    assert _src_do_simbolo(cliente).startswith("/logos/cla-")


def test_logo_torto_nao_deixa_cla_pela_metade(app_web):
    """O arquivo e conferido ANTES de escrever qualquer coisa.

    Se a conferencia viesse depois, este pedido teria criado conta e cla e precisaria desfazer os
    dois. A prova e que o email continua livre: dava para tentar de novo com ele.
    """
    cliente = _cliente(app_web)
    recusa = cliente.post(
        "/criar-cla",
        data={
            "nome_cla": "Cla que Nao Nasce",
            "nome": "Kiko Tester",
            "email": "kiko@cla.com",
            "telefone": "11912340004",
            "senha": "senhaforte1",
        },
        files={"logo": ("logo.png", b"isto nao e uma imagem", "image/png")},
    )
    assert recusa.status_code == 400
    assert "PNG" in recusa.text

    from app.database import SessionLocal
    from app.repositorios import contas as repo_contas

    db = SessionLocal()
    try:
        assert repo_contas.usuario_por_email(db, "kiko@cla.com") is None
    finally:
        db.close()


def test_convite_valido_tem_botao_de_copiar_com_o_mesmo_link(carla, gerar_convite):
    """O Copiar leva o link do `data-copiar`, e ele tem que ser IGUAL ao do campo que a pessoa ve.

    Se os dois fossem montados em lugares diferentes, um dia o campo mostraria um endereco e o botao
    copiaria outro, e ninguem perceberia ate um convite nao abrir no WhatsApp de alguem.
    """
    import re

    convite_id, token = gerar_convite(carla, dias=7, max_usos="")
    pagina = carla.get("/cla").text
    copiar = re.search(r'data-copiar="([^"]*/convite/' + re.escape(token) + r')"', pagina)
    assert copiar is not None, "o convite valido nao tem botao de copiar"
    assert f'value="{copiar.group(1)}"' in pagina, (
        "o botao copia um link diferente do que o campo mostra"
    )
    depois = pagina[copiar.end() :]
    assert depois.find(f"/cla/convites/{convite_id}/revogar") != -1, (
        "o Copiar deveria vir antes do Revogar"
    )

    carla.post(f"/cla/convites/{convite_id}/revogar", follow_redirects=True)
    assert re.search(r'data-copiar="[^"]*' + re.escape(token), carla.get("/cla").text) is None, (
        "convite revogado continua com botao de copiar"
    )
