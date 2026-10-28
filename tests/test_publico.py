"""O que um visitante sem login enxerga: tela de entrada, estaticos e PWA.

Nada aqui depende de conta criada, entao cada teste e independente dos outros.
"""

from __future__ import annotations

import re


def test_visitante_vai_para_o_login(visitante):
    resposta = visitante.get("/", follow_redirects=False)
    assert resposta.headers.get("location") == "/login"


def test_login_oferece_criar_um_cla(visitante):
    # Era "/criar-conta". A conta nao nasce mais solta: ela nasce junto com o cla que ela abriu.
    assert "/criar-cla" in visitante.get("/login").text


# A marca sao DOIS arquivos, um por tema, porque a assinatura tem duas cores e elas vao para lados
# opostos quando o fundo da pagina troca. Quem gera e o scripts/arte.py; o que cada uma mostra o
# tests/test_estilo.py confere contra as variaveis do CSS.
MARCAS = {"claro": "/static/marca-no-claro.png", "escuro": "/static/marca-no-escuro.png"}


def test_na_tela_de_entrar_a_arte_e_o_titulo(visitante):
    """A assinatura ja escreve "subidoCLA", entao o nome nao aparece uma segunda vez em texto.

    Havia ali um `<div class="marca">{{ cla_nome }}</div>`, e nesta tela `cla_nome` sempre cai no
    nome do app, porque ninguem esta logado e nao existe cla ativo para nomear: era o mesmo nome
    escrito duas vezes, um embaixo do outro. A assercao de ausencia e o que impede isso de voltar
    quando alguem olhar o template do lado e achar que falta um titulo aqui.

    O `.marca` nao existe em lugar nenhum desta pagina: o do cabecalho so e desenhado para quem esta
    logado. Entao procurar a classe inteira, e nao so o texto, e o que pega tambem a volta disfarcada
    de um titulo escrito na mao.
    """
    texto = visitante.get("/login").text
    for endereco in MARCAS.values():
        assert endereco in texto, f"{endereco} sumiu da tela de entrar"
    assert 'class="marca"' not in texto, "a tela de entrar voltou a escrever o nome embaixo da arte"


def test_marca_aparece_acima_do_titulo_na_tela_de_criar_cla(visitante):
    """Onde ainda ha titulo escrito, a arte vem ANTES dele.

    Esta tela mantem o `.marca` porque la ele diz outra coisa: "Criar um cla", que e informacao que a
    assinatura nao carrega. O que se confere e a ordem, que e o que faz a assinatura ser assinatura e
    nao uma ilustracao solta no meio da pagina.

    O titulo procurado e o VISIVEL, dentro da `.marca`, e nao a primeira ocorrencia do texto na
    pagina: o `<head>` traz o nome do app numa meta tag de PWA, que vem antes de qualquer coisa do
    corpo e faria esta ordem passar por um motivo que nao tem nada a ver com esta tela.
    """
    texto = visitante.get("/criar-cla").text
    titulo = texto.index('<div class="marca">Criar um <span>')
    for arquivo in MARCAS.values():
        assert texto.index(arquivo) < titulo, f"{arquivo} aparece depois do titulo da tela"


def test_arquivo_da_marca_e_servido(visitante):
    for endereco in MARCAS.values():
        resposta = visitante.get(endereco)
        assert resposta.status_code == 200, f"{endereco} nao responde"
        assert resposta.content[:8] == b"\x89PNG\r\n\x1a\n", f"{endereco} nao e PNG"


def _arte_da_marca(visitante, tema: str):
    """A marca como o navegador a recebe, aberta de verdade em vez de suposta pelo nome do arquivo.

    RGBA e nao RGB porque o alfa e metade do que se quer provar aqui: a marca nao tem fundo.
    """
    from io import BytesIO

    from PIL import Image

    return Image.open(BytesIO(visitante.get(MARCAS[tema]).content)).convert("RGBA")


def test_marca_carrega_na_proporcao_do_proprio_arquivo(visitante):
    """width/height no HTML, conferidos contra o PNG servido em vez de repetidos a mao.

    Os dois numeros existem para a arte reservar o lugar certo enquanto a folha nao chegou. Escritos
    a mao, eles envelhecem calados: a marca ja trocou de proporcao duas vezes, e numero velho aqui
    nao reserva espaco, estica a arte. Comparar com o arquivo e o que faz esta assercao continuar
    querendo dizer alguma coisa depois da proxima troca de arte.
    """
    texto = visitante.get("/login").text
    for tema in MARCAS:
        achado = re.search(
            rf'class="marca-arte marca-no-{tema}"[^>]*width="(\d+)" height="(\d+)"', texto
        )
        assert achado is not None, f"a marca do tema {tema} saiu sem width/height no HTML"
        largura, altura = int(achado.group(1)), int(achado.group(2))

        arte = _arte_da_marca(visitante, tema)
        esperado = arte.width / arte.height
        assert abs(largura / altura - esperado) < 0.03, (
            f"{tema}: o HTML pede {largura}x{altura} e o arquivo e {arte.width}x{arte.height}"
        )


def test_marca_nao_tem_fundo_proprio(visitante):
    """A assinatura pousa no fundo da pagina; ela nao e um retangulo colorido colado por cima.

    Isso ja veio errado uma vez: a marca saiu com o azul do arquivo de origem junto, e na tela virou
    um quadrado azul no meio do layout. Um PNG com fundo passa por qualquer teste que so olhe nome
    de arquivo e tamanho, entao o que se confere e o alfa.

    Duas assercoes e nao uma. A quina prova que nao ha retangulo. A CONTAGEM prova que o vazio e a
    maior parte da imagem: uma arte com fundo quase opaco e quina transparente por acaso passaria na
    primeira e reprovaria aqui.
    """
    for tema in MARCAS:
        arte = _arte_da_marca(visitante, tema)
        assert arte.getpixel((0, 0))[3] == 0, f"{tema}: a quina da marca e opaca, tem fundo ali"

        pixels = list(arte.get_flattened_data())
        vazio = sum(1 for cor in pixels if cor[3] == 0)
        assert vazio > len(pixels) / 2, (
            f"{tema}: so {vazio} de {len(pixels)} pixels sao vazios, a marca tem fundo"
        )


def test_marca_traz_a_assinatura_inteira_e_nao_so_o_cla(visitante):
    """A arte e "subido" mais "CLÃ", e nao o "CLÃ" sozinho.

    Isso ja deu errado uma vez, e em silencio: o arquivo de origem veio com o "subido" em BRANCO
    sobre fundo BRANCO, entao a palavra estava la e era invisivel. O recorte tirado dele saiu com o
    "CLÃ" e mais nada, e passou por bom porque ninguem enxerga um PNG de dentro de um teste.

    O que separa os dois casos e a contagem de tintas: a assinatura inteira e desenhada em DUAS
    cores chapadas, com area de sobra em cada uma. So o "CLÃ" seria uma cor so.
    """
    from collections import Counter

    for tema in MARCAS:
        arte = _arte_da_marca(visitante, tema)
        # So o que esta cheio: a borda das letras e mistura com o vazio e nao e tinta de ninguem.
        tintas = Counter(cor[:3] for cor in arte.get_flattened_data() if cor[3] == 255)
        assert len(tintas) >= 2, f"{tema}: a marca tem uma cor so, falta uma das duas palavras"

        (uma, quanto_uma), (outra, quanto_outra) = tintas.most_common(2)
        assert quanto_outra > 500, (
            f"{tema}: a segunda cor tem so {quanto_outra} pixels, e sobra de borda e nao palavra"
        )
        assert sum(abs(a - b) for a, b in zip(uma, outra)) > 90, (
            f"{tema}: as duas tintas {uma} e {outra} sao quase a mesma cor"
        )
        assert quanto_uma > 500


def test_css_sai_versionado_e_o_endereco_responde(visitante):
    texto = visitante.get("/login").text
    versao = re.search(r"/static/style\.css\?v=(\d+)", texto)
    assert versao is not None
    assert visitante.get(f"/static/style.css?v={versao.group(1)}").status_code == 200


def test_manifesto_responde_na_raiz_sem_login(visitante):
    # O Chrome busca o manifesto sem cookie, entao ele nao pode depender de login.
    resposta = visitante.get("/manifest.webmanifest")
    assert resposta.status_code == 200
    assert resposta.json()["start_url"] == "/"


def test_manifesto_tem_icone_de_512(visitante):
    icones = visitante.get("/manifest.webmanifest").json()["icons"]
    assert any(icone["sizes"] == "512x512" for icone in icones)


def test_o_icone_sai_versionado_na_pagina_e_no_manifesto(visitante):
    """Trocar a arte do icone tem que trocar o ENDERECO dele, senao ninguem ve a arte nova.

    Isto aconteceu de verdade: o app subiu renomeado para Subido Cla, com o icone azul no lugar do
    brasao laranja, e a aba do navegador continuou laranja. O arquivo em producao era o novo, byte
    a byte; o endereco e que era o mesmo de antes. Favicon e icone de app instalado sao guardados
    por endereco, e em lugares que nao sao o cache de HTTP, entao nao adianta o servidor mandar
    bytes novos num endereco que o navegador considera que ja conhece.

    O teste cobre os dois lados porque sao dois consumidores diferentes: a aba le o <link> do HTML,
    e o icone do app instalado le o manifesto. Versionar so um deixa o outro velho.
    """
    versao = re.search(r"/static/icone-192\.png\?v=(\d+)", visitante.get("/login").text)
    assert versao is not None, "o <link rel=icon> da pagina esta sem ?v="
    assert visitante.get(f"/static/icone-192.png?v={versao.group(1)}").status_code == 200

    for icone in visitante.get("/manifest.webmanifest").json()["icons"]:
        assert re.search(r"\?v=\d+$", icone["src"]), f"{icone['src']} no manifesto esta sem ?v="


def test_manifesto_e_service_worker_sempre_revalidam(visitante):
    """Os dois arquivos que ensinam o resto nao podem ser servidos de um cache sem perguntar.

    O manifesto diz qual icone o app instalado usa e o sw diz o que fica guardado para o offline.
    Guardados sem revalidar, eles congelam a versao anterior do app inteiro em quem ja abriu uma
    vez, e o sintoma nao parece cache: parece deploy que nao subiu.
    """
    for endereco in ("/manifest.webmanifest", "/sw.js"):
        cabecalho = visitante.get(endereco).headers.get("cache-control", "")
        assert "no-cache" in cabecalho, f"{endereco} saiu com cache-control {cabecalho!r}"


def test_service_worker_sai_da_raiz(visitante):
    # O service worker so controla o que esta dentro do escopo dele.
    resposta = visitante.get("/sw.js")
    assert resposta.status_code == 200
    assert '"fetch"' in resposta.text


def test_icone_512_e_um_png_de_verdade(visitante):
    assert visitante.get("/static/icone-512.png").content[:8] == b"\x89PNG\r\n\x1a\n"


def test_pagina_aponta_para_o_manifesto(visitante):
    assert '<link rel="manifest" href="/manifest.webmanifest">' in visitante.get("/login").text


# ---------- tema claro e escuro ----------


def test_pagina_nasce_com_um_tema_valido_sem_js(visitante):
    # O tema padrao esta escrito no proprio HTML. Se dependesse do script, quem esta com JS ainda
    # baixando (ou bloqueado) veria a pagina sem tema nenhum, com as variaveis de cor vazias.
    assert '<html lang="pt-BR" data-tema="claro">' in visitante.get("/login").text


def test_script_do_tema_roda_antes_da_folha_de_estilo(visitante):
    """A ORDEM e a funcionalidade inteira aqui, e e o tipo de coisa que se perde num refactor.

    O script le o localStorage e troca o `data-tema` antes da primeira pintura. Empurrado para o
    fim do corpo (que e onde todo mundo poe script, e por bons motivos), ele continua funcionando
    e o teste continua passando: a diferenca e que quem escolheu escuro passa a ver a tela clara
    piscar em TODA navegacao. Nenhuma assercao sobre presenca pega isso, so uma sobre posicao.
    """
    texto = visitante.get("/login").text
    assert texto.index('localStorage.getItem("tema")') < texto.index("/static/style.css")


def test_botao_de_tema_aparece_logado_e_deslogado(visitante, carla):
    # Sao dois lugares diferentes no base.html: pendurado no cabecalho de quem entrou e solto no
    # canto de quem ainda nao entrou. A tela de login e justamente onde o app e visto pela
    # primeira vez, entao esquecer o botao la seria esquece-lo na primeira impressao.
    assert "data-tema-botao" in visitante.get("/login").text
    assert "data-tema-botao" in carla.get("/").text


def test_botao_nasce_escondido_e_so_o_script_mostra(visitante):
    # Sem JS nao ha onde guardar a escolha, entao o botao nao pode aparecer: um botao que nao faz
    # nada ao ser clicado e pior do que um botao que nao existe.
    texto = visitante.get("/login").text
    assert re.search(r"<button[^>]*data-tema-botao[^>]*\shidden", texto) is not None
    assert "botao.hidden = false" in texto


def test_botao_de_tema_e_icone_e_mesmo_assim_tem_nome(visitante):
    """O botao virou desenho, e desenho nao tem nome.

    Ele dizia "Claro" e "Escuro"; agora sao a lua e o sol, que e a convencao de todo app que tem esta
    troca. O que se perde nessa troca, e em silencio, e o nome: um leitor de tela em cima de um botao
    so com `<svg>` dentro anuncia "botao" e para por ai. Por isso o texto continua no HTML, num
    `.so-leitor`, que sai da TELA sem sair da arvore de acessibilidade.

    Dois de cada porque os dois estados vao juntos no HTML sempre, e quem escolhe um e o CSS: e isso
    que faz o icone certo aparecer ja na primeira pintura, sem piscar do errado para o certo.
    """
    texto = visitante.get("/login").text
    botao = re.search(r"<button[^>]*data-tema-botao.*?</button>", texto, re.S)
    assert botao is not None, "o botao de tema sumiu da tela de entrar"
    marcacao = botao.group(0)

    assert marcacao.count("<svg") == 2, "o botao de tema nao tem os dois icones"
    assert marcacao.count('class="so-leitor"') == 2, (
        "o botao de icone ficou sem nome: um leitor de tela vai anunciar so 'botao'"
    )


def test_css_traz_os_dois_temas(visitante):
    folha = visitante.get("/static/style.css").text
    # O claro e o padrao, escrito no :root. O escuro so existe se houver um bloco que o sobrescreva:
    # sem ele o botao troca o atributo e nada muda na tela.
    assert '[data-tema="escuro"]' in folha
