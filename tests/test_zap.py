"""O canal de ajuda: o botao redondo do cabecalho e o link discreto das telas de entrada.

Sao cinco lugares que apontam para o MESMO telefone, e e essa repeticao que estes testes vigiam.
Um numero de WhatsApp escrito a mao em cinco templates nao da erro nenhum quando alguem troca de
numero: quatro telas passam a levar para o telefone certo e a quinta continua levando para o antigo,
e o jeito de descobrir e alguem do outro lado receber uma mensagem que nao era para ele.

O link e a unica forma de quem esta preso falar com quem cuida do app. Ele nao pode existir so nas
telas que estavam abertas no dia em que foi escrito.
"""

from __future__ import annotations

import re
from pathlib import Path

# Escrito aqui por extenso de proposito. Se este numero mudar, o teste reprova e obriga quem mudou
# a olhar esta linha, que e onde esta escrito o que o numero significa. Importar `ZAP_SUPORTE` do
# config faria o teste concordar com qualquer coisa que estivesse la, inclusive com um dedo errado.
NUMERO = "5511976012274"
LINK = f"https://wa.me/{NUMERO}"

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


def test_o_numero_esta_escrito_num_lugar_so():
    """Nenhum template conhece o telefone: todos recebem o endereco pronto pelo global `url_zap`.

    Esta e a assercao que protege as outras quatro. Elas conferem que o link certo aparece em cada
    tela, e passariam igual com o numero copiado template a template, que e exatamente o arranjo que
    quebra no dia da troca. O que se procura aqui e o RASTRO de uma copia, e nao o link certo.
    """
    for arquivo in TEMPLATES.rglob("*.html"):
        texto = arquivo.read_text(encoding="utf-8")
        assert "wa.me" not in texto, f"{arquivo.name} escreveu o endereco do WhatsApp na mao"
        assert "976012274" not in texto, f"{arquivo.name} escreveu o telefone na mao"


def _zap_do_cabecalho(texto: str) -> str | None:
    achado = re.search(r'<a class="btn btn-mini btn-zap".*?</a>', texto, re.S)
    return achado.group(0) if achado else None


def test_o_botao_do_zap_esta_no_cabecalho_de_quem_entrou(ana):
    botao = _zap_do_cabecalho(ana.get("/").text)
    assert botao is not None, "o botao do WhatsApp sumiu do cabecalho"
    assert LINK in botao, f"o botao do cabecalho aponta para outro lugar: {botao}"


def test_o_botao_do_zap_fica_entre_o_nome_e_o_sair(ana):
    """A ordem pedida, e ela tem consequencia: o Sair e o vizinho mais caro que existe.

    Empurrado para depois do Sair, o botao passa a ser o alvo errado de quem mira o certo, num canto
    de tela onde os dois tem 32px. A ordem no HTML e a ordem na tela porque o `.topo-dir` e um flex
    sem reordenacao.
    """
    texto = ana.get("/").text
    dir_ = re.search(r'<div class="topo-dir">.*?</div>\s*</div>', texto, re.S)
    assert dir_ is not None, "o cabecalho perdeu o bloco da direita"
    bloco = dir_.group(0)
    assert bloco.index('class="quem"') < bloco.index("btn-zap") < bloco.index("/sair"), (
        "o botao do WhatsApp saiu do lugar: ele vai entre o nome e o Sair"
    )


def test_o_botao_do_zap_nao_some_no_celular(ana, visitante):
    """Ele fica FORA do `<span class="quem">`, e isso e funcionalidade, nao arrumacao.

    O media query do celular faz `.quem { display: none }`. Um botao aninhado ali dentro desaparece
    junto, em silencio: a tela continua inteira, o teste de presenca acima continua passando, e o
    canal de ajuda deixa de existir exatamente no aparelho onde o app e mais usado.

    As duas pontas sao conferidas na mesma assercao porque uma sem a outra nao quer dizer nada: se
    um dia o CSS parar de esconder o `.quem`, esta prova vira uma regra sobre um perigo que nao
    existe mais, e reprovar aqui e o aviso de que ela precisa ser relida.
    """
    folha = visitante.get("/static/style.css").text
    assert re.search(r"\.quem\s*\{\s*display:\s*none", folha) is not None, (
        "o CSS nao esconde mais o nome no celular: esta assercao precisa ser relida"
    )

    nome = re.search(r'<span class="quem">.*?</span>', ana.get("/").text, re.S)
    assert nome is not None
    assert "btn-zap" not in nome.group(0), (
        "o botao do WhatsApp foi parar dentro do nome, e o celular esconde o nome inteiro"
    )


def test_o_botao_do_zap_e_desenho_e_mesmo_assim_tem_nome(ana):
    """Mesma regra do botao de tema: icone sozinho nao tem nome, e leitor de tela anuncia "link".

    `.so-leitor` e o jeito da casa de escrever nome que sai da tela sem sair da arvore de
    acessibilidade. `display:none` ali dentro apagaria o nome para os dois.
    """
    botao = _zap_do_cabecalho(ana.get("/").text)
    assert botao is not None
    assert "<svg" in botao, "o botao do WhatsApp ficou sem o simbolo"
    assert 'class="so-leitor"' in botao, (
        "o botao do WhatsApp e so desenho e ficou sem nome: um leitor de tela vai anunciar 'link'"
    )


def _telas_publicas(visitante, gerar_convite, carla):
    _, token = gerar_convite(carla, dias=7, max_usos="")
    return {
        "/login": visitante.get("/login").text,
        "/criar-cla": visitante.get("/criar-cla").text,
        "/tutorial": visitante.get("/tutorial").text,
        f"/convite/{token}": visitante.get(f"/convite/{token}").text,
    }


def test_o_link_de_ajuda_aparece_em_toda_tela_de_entrada(visitante, gerar_convite, carla):
    """As quatro telas onde a pessoa ainda nao tem cabecalho para pendurar o botao redondo.

    Sao justamente as telas onde alguem trava: nao consegue entrar, nao entende o que e um cla, ou
    recebeu um link e nao sabe de quem. Sem o cabecalho, este link e a unica saida.
    """
    for endereco, texto in _telas_publicas(visitante, gerar_convite, carla).items():
        assert 'class="ajuda"' in texto, f"{endereco} ficou sem o link de tirar duvidas"
        assert LINK in texto, f"{endereco} tem o link mas aponta para outro numero"


def test_o_link_de_ajuda_aparece_tambem_no_convite_que_nao_serve(visitante):
    """A ramificacao mais precisa dele, e a que uma refatoracao esquece primeiro.

    Quem chega com token vencido ou inventado ve "este link nao serve mais" e nada mais: nao sabe
    quem convidou, nao sabe qual cla era, e a tela de proposito nao conta. O include mora fora do
    `{% if %}` por isso, e este teste e o que impede alguem mover ele para dentro de um dos ramos
    bonitos sem perceber que apagou a saida do ramo feio.
    """
    texto = visitante.get("/convite/isto-nao-existe").text
    assert "Este link não serve mais." in texto, "a tela de convite recusado mudou de forma"
    assert LINK in texto, "o convite recusado ficou sem o link de ajuda"


def test_a_conversa_ja_chega_escrita_do_outro_lado(visitante):
    """Sem texto pronto chega um "oi" sozinho, e do outro lado nao da para saber do que se trata.

    O `?text=` e o que transforma a mensagem em pergunta com contexto. Ele tem que estar CODIFICADO:
    espaco cru na query faz o WhatsApp abrir a conversa com o texto cortado no primeiro espaco.

    O recorte vai ate a ASPA de fechamento do href, e nao ate o primeiro espaco. Parece detalhe e e
    o teste inteiro: recortado no espaco, o pedaco capturado nunca teria espaco dentro, e a assercao
    seguinte passaria por construcao. Foi assim que este teste nasceu, e so a mutacao mostrou.
    """
    texto = visitante.get("/login").text
    achado = re.search(rf'href="{re.escape(LINK)}\?text=([^"]*)"', texto)
    assert achado is not None, "o link de ajuda abre a conversa vazia"
    assert achado.group(1), "o `?text=` esta la mas a mensagem esta em branco"
    assert " " not in achado.group(1), "o texto da conversa saiu sem codificar e vai chegar cortado"


def test_todo_link_de_zap_abre_fora_e_sem_dar_o_app_de_presente(ana, visitante):
    """`target="_blank"` sem `rel="noopener"` entrega `window.opener` para a outra aba.

    No cabecalho isso e pior: quem clica ali esta logado. A pagina aberta ganha o poder de trocar o
    endereco da aba de origem, que e o jeito classico de mostrar uma tela de login falsa para alguem
    que acabou de sair de uma de verdade. Sao dois lugares diferentes no HTML (o botao e o link), e
    os dois sao conferidos porque o descuido cabe em qualquer um dos dois.
    """
    for onde, texto in (("cabecalho", ana.get("/").text), ("login", visitante.get("/login").text)):
        for ancora in re.findall(r"<a[^>]*wa\.me[^>]*>", texto):
            assert 'target="_blank"' in ancora, f"{onde}: o WhatsApp abre por cima do app"
            assert "noopener" in ancora, f"{onde}: link com target=_blank sem rel=noopener"
