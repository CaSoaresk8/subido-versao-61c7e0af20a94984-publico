"""O video que explica o app, nos tres lugares onde ele aparece.

Sao a tela /tutorial (aberta pelo menu de quem esta logado) e a dobra das duas telas de entrada,
login e criar cla. Nas telas de entrada ele abre ALI, sem navegar: quem esta com o formulario meio
preenchido nao pode perder o que digitou para assistir a uma explicacao.

O arquivo e o mais pesado que o app serve, 21 MB, e quase tudo que se confere aqui existe por causa
desse numero: um video pode estar visivel e funcionando na tela e mesmo assim estar custando caro a
quem nunca clicou nele.
"""

from __future__ import annotations

import re


def test_tutorial_abre_sem_login(visitante):
    """Publica de proposito: ela aparece na tela de criar cla, onde ninguem tem conta ainda.

    Se um dia alguem pendurar `escopo_logado` nessa rota, o link da tela de criar cla passa a mandar
    o visitante para o login, que e exatamente a pessoa que mais precisa do video.

    `follow_redirects=False` e o que faz esta assercao querer dizer alguma coisa, e isso foi
    descoberto quebrando a rota de proposito para ver o teste reprovar: ele nao reprovou. O
    `escopo_logado` responde 303 para /login, o cliente de teste segue o desvio sozinho, e o 200 que
    chegava aqui era o da TELA DE LOGIN. O teste afirmava "o tutorial abre" olhando para outra
    pagina. Sem o desvio, 303 e 200 deixam de ser a mesma coisa.
    """
    resposta = visitante.get("/tutorial", follow_redirects=False)
    assert resposta.status_code == 200, (
        f"/tutorial respondeu {resposta.status_code} para quem nao esta logado"
    )
    assert "<video" in resposta.text


def test_tutorial_abre_logado_e_com_o_menu_inteiro(ana):
    """Quem esta logado precisa do cabecalho aqui, senao o tutorial vira um beco.

    A rota nao exige sessao, e por isso e possivel ela responder sem escopo mesmo para quem TEM
    sessao: bastaria trocar a dependencia por uma que nao passe pelo `escopo_opcional`, e a pagina
    continuaria abrindo 200, so que sem topo e sem jeito de voltar. A prova e a barra de navegacao,
    que o base.html so desenha quando existe membro.
    """
    texto = ana.get("/tutorial").text
    assert '<nav class="nav">' in texto, "quem esta logado caiu na versao de visitante do tutorial"


def test_visitante_tem_para_onde_ir_depois_do_video(visitante):
    # Sem cabecalho na tela, estes dois links sao a unica saida de quem chegou deslogado.
    texto = visitante.get("/tutorial").text
    assert "/criar-cla" in texto
    assert "/login" in texto


def test_o_menu_leva_ao_tutorial(ana):
    nav = re.search(r'<nav class="nav">(.*?)</nav>', ana.get("/").text, re.S)
    assert nav is not None
    assert 'href="/tutorial"' in nav.group(1), "o Tutorial sumiu do menu"


TELAS_DE_ENTRADA = ("/login", "/criar-cla")


def test_as_telas_de_entrada_trazem_a_dobra_com_o_video(visitante):
    """As duas, e pelo mesmo motivo: quem chega sem saber o que e isto chega por uma delas.

    O login era a que faltava. Ele e a porta que a maioria das pessoas ve primeiro, inclusive quem
    recebeu o endereco de alguem e nunca abriu o app, e ate ontem era a unica tela de entrada sem o
    video a um clique.

    `<details>` e o que faz "escondido" ser de verdade. Se um dia isso virar uma div sempre aberta,
    o teste do `preload="none"` continua passando e mesmo assim a tela muda de carater: o video
    passa a ocupar a tela de quem so queria digitar email e senha.
    """
    for endereco in TELAS_DE_ENTRADA:
        texto = visitante.get(endereco).text
        assert "tutorial-dobra" in texto, f"{endereco} ficou sem a dobra do tutorial"
        assert "<details" in texto, f"{endereco}: a dobra deixou de comecar fechada"
        assert "/static/tutorial.mp4" in texto, f"{endereco}: a dobra ficou sem o video dentro"


def test_a_dobra_abre_o_video_sem_tirar_a_pessoa_da_tela(visitante):
    """O pedido em uma frase: o video aparece ALI, e nao numa pagina nova.

    E a assercao que o teste acima nao faz. Um `<a href="/tutorial">` ao lado de um `<details>`
    vazio passaria por ele: a dobra existe, o video existe, e mesmo assim o clique leva a pessoa
    para outro lugar e ela perde o que tinha digitado no formulario.

    Entao o que se procura aqui e o contrario de uma presenca: NAO pode haver link para /tutorial
    nestas telas. O video tem que estar dentro da propria dobra, e nao atras de um endereco.
    """
    import re as _re

    for endereco in TELAS_DE_ENTRADA:
        texto = visitante.get(endereco).text
        assert 'href="/tutorial"' not in texto, (
            f"{endereco} manda a pessoa para outra pagina em vez de abrir o video na propria tela"
        )
        dobra = _re.search(r'<details class="tutorial-dobra">.*?</details>', texto, _re.S)
        assert dobra is not None, f"{endereco}: a dobra mudou de forma"
        assert "<video" in dobra.group(0), (
            f"{endereco}: o player esta fora da dobra, entao abrir a dobra nao mostra video nenhum"
        )


def test_a_dobra_e_a_mesma_nas_duas_telas(visitante):
    """Escrita num include so. Duas copias do mesmo `<details>` divergem sem dar erro nenhum.

    O sintoma seria mudo: alguem melhora o texto do resumo numa tela, a outra continua com o antigo,
    e o jeito de descobrir e comparar as duas telas lado a lado, que ninguem faz.
    """
    import re as _re

    def dobra(endereco: str) -> str:
        achado = _re.search(
            r'<details class="tutorial-dobra">.*?</details>', visitante.get(endereco).text, _re.S
        )
        assert achado is not None, f"{endereco} perdeu a dobra"
        return achado.group(0)

    assert dobra("/login") == dobra("/criar-cla"), (
        "as duas telas de entrada tem dobras diferentes: alguma delas foi copiada em vez de incluida"
    )


def test_o_video_nao_comeca_a_baixar_sozinho(visitante):
    """A assercao mais importante deste arquivo, e a que nao da sintoma nenhum quando quebra.

    Sem `preload="none"`, o navegador comeca a buscar o video assim que a pagina abre. A tela continua
    identica, o formulario continua funcionando, e a unica diferenca e que criar um cla passa a custar
    dezenas de MB para uma pessoa que talvez nunca clique no tutorial. E pior no celular, que e onde o
    app e usado. O `poster` e o outro lado da mesma moeda: sem ele, `preload="none"` deixaria um
    retangulo preto no lugar do video.
    """
    for endereco in (*TELAS_DE_ENTRADA, "/tutorial"):
        texto = visitante.get(endereco).text
        player = re.search(r"<video[^>]*>", texto)
        assert player is not None, f"{endereco} nao tem player"
        assert 'preload="none"' in player.group(0), (
            f"{endereco}: o video baixa sozinho ao abrir a pagina"
        )
        assert "poster=" in player.group(0), f"{endereco}: sem poster, o player fica preto"


def test_video_e_capa_saem_versionados_e_respondem(visitante):
    """Mesma regra do css e do icone, e aqui ela pesa mais: e o arquivo mais caro de rebaixar.

    Quem ja assistiu tem 21 MB guardados. Sem numero no endereco, uma regravacao do tutorial nao
    chega nessa pessoa, e o sintoma e o pior possivel: o video toca normalmente, so que e o antigo.
    """
    texto = visitante.get("/tutorial").text
    for arquivo in ("tutorial.mp4", "tutorial-capa.jpg"):
        versao = re.search(rf"/static/{re.escape(arquivo)}\?v=(\d+)", texto)
        assert versao is not None, f"{arquivo} saiu sem ?v="
        resposta = visitante.get(f"/static/{arquivo}?v={versao.group(1)}")
        assert resposta.status_code == 200, f"{arquivo} nao responde no endereco versionado"


def test_o_arquivo_servido_e_um_mp4_que_o_navegador_toca(visitante):
    """Abre o arquivo em vez de confiar na extensao, e confere onde esta o indice.

    `ftyp` no comeco e o que faz o arquivo ser um mp4, e nao um arquivo qualquer com o nome certo.

    O `moov` e a parte que importa para quem assiste: e o indice, e o ffmpeg o escreve no FIM por
    padrao. Um mp4 sem `+faststart` funciona perfeitamente no computador de quem gravou e, servido
    pela web, obriga o navegador a baixar os 21 MB inteiros antes de mostrar o primeiro quadro. O
    teste le os primeiros atoms e exige o `moov` antes do `mdat`, que e o bloco com o video de fato.
    """
    dados = visitante.get("/static/tutorial.mp4").content
    assert dados[4:8] == b"ftyp", "o tutorial.mp4 nao e um mp4"

    ordem, pos = [], 0
    while pos + 8 <= len(dados) and len(ordem) < 8:
        tamanho = int.from_bytes(dados[pos : pos + 4], "big")
        ordem.append(dados[pos + 4 : pos + 8].decode("latin1"))
        if tamanho <= 0:
            break
        pos += tamanho

    assert "moov" in ordem, f"nao achei o indice do video nos primeiros atoms: {ordem}"
    assert ordem.index("moov") < ordem.index("mdat"), (
        f"o indice do video esta depois do conteudo ({ordem}): faltou +faststart, e o navegador vai "
        "ter que baixar o arquivo inteiro antes do primeiro quadro"
    )


def test_o_servidor_aceita_pedir_um_pedaco_do_video(visitante):
    """Range e o que faz arrastar a barra do player pular para o minuto pedido.

    Sem resposta 206, o player so consegue tocar do comeco, e cada pulo na barra vira download do
    arquivo todo de novo. Quem implementa isso e o StaticFiles, e o teste existe para o caso de
    alguem trocar a forma de servir esse arquivo por um FileResponse escrito na mao, que nao faz
    Range e nao reclama de nao fazer.
    """
    resposta = visitante.get("/static/tutorial.mp4", headers={"Range": "bytes=0-1023"})
    assert resposta.status_code == 206, "o servidor ignorou o Range e mandou o arquivo inteiro"
    assert len(resposta.content) == 1024


def test_o_service_worker_nao_guarda_o_video(visitante):
    """O sw guarda TODA resposta ok de /static/, e o video nao pode entrar nessa regra.

    Dois estragos, e o teste cobre os dois de uma vez porque a correcao e a mesma linha. Tamanho:
    21 MB no armazenamento do navegador de cada pessoa que assistir, para um video que se ve uma vez.
    E os pedacos: player pede com Range e recebe 206, `cache.put` recusa 206, e a recusa vira erro
    solto no console a cada pedaco.

    A assercao e sobre a ORDEM, e nao sobre a presenca do `.mp4` no arquivo: a saida antecipada so
    protege se vier ANTES do bloco que guarda o /static/. Escrita depois dele, ela nunca e alcancada,
    e o `.mp4` estaria la no codigo para quem lesse, sem fazer efeito nenhum.
    """
    sw = visitante.get("/sw.js").text
    saida = sw.find('endsWith(".mp4")')
    assert saida != -1, "o service worker voltou a guardar o video no cache do navegador"
    assert saida < sw.find('startsWith("/static/")'), (
        "a saida do .mp4 esta depois da regra do /static/, entao ela nunca roda"
    )


def test_controle_de_velocidade_junto_do_video_nas_tres_telas(visitante):
    """O controle de 0,1 em 0,1 mora no `_tutorial.html`, entao tem que aparecer onde o video aparece.

    Dentro do MESMO `[data-player]` do video: o JS acha o video subindo do botao ate o player, e um
    controle fora dele nao teria video nenhum para acelerar. Nasce `hidden` porque sem JS nao faz nada.
    """
    for rota in ("/login", "/criar-cla", "/tutorial"):
        texto = visitante.get(rota).text
        player = re.search(
            r'<div class="tutorial-player" data-player>(.*?)</div>\s*</div>', texto, re.S
        )
        assert player is not None, f"{rota}: o video nao esta dentro de um [data-player]"
        bloco = player.group(1)
        assert "<video" in bloco, f"{rota}: o [data-player] nao tem o video"
        barra = re.search(r"<div[^>]*data-velocidade[^>]*>", bloco)
        assert barra is not None, f"{rota}: sem controle de velocidade junto do video"
        assert "hidden" in barra.group(0), f"{rota}: o controle aparece mesmo sem JS"
        assert 'data-vel="-1"' in bloco and 'data-vel="1"' in bloco, f"{rota}: falta - ou +"
        assert ">1,0x<" in bloco, f"{rota}: a velocidade nao comeca em 1,0x"
