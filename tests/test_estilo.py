"""Contraste das cores dos dois temas, conferido por conta e nao por olho.

Cor e a unica parte do visual que da para verificar sem abrir navegador, e e justamente a que
engana quem esta olhando: um verde bonito num monitor bom, de dia, parece legivel, e some no
celular de outra pessoa no sol. O numero nao tem essa opiniao.

O criterio e o WCAG 2.1 AA para texto normal, 4.5:1. Nao e AAA porque a barra la e 7:1 e derrubaria
metade de uma paleta que ja esta boa; nao e o 3:1 de texto grande porque as cores testadas aqui
aparecem em selo de 11px e titulo de 11px, que e o oposto de texto grande.

Duas coisas fizeram este arquivo crescer, e as duas sao a mesma licao: **o fundo certo e aquele
onde a cor aparece de verdade, nao o mais obvio.**

1. O selo nao fica sobre o fundo do card. Ele fica sobre a propria cor a 12% (`--ok-soft`), entao
   a conta correta e contra a mistura. Medir contra o branco dava 3.77 e parecia quase passar;
   contra a mistura real dava 3.25.
2. Medir so contra `--surface` (o branco do card) deixou passar quatro cores. `--muted` e
   `--danger` davam 4.8 no branco e reprovavam em `--surface-2`, que e o fundo dos botoes, onde o
   "Revogar" mora. `--prata` e `--bronze`, o segundo e o terceiro lugar do ranking, davam 2.37 e
   3.38 em qualquer fundo do tema claro. Isso so apareceu quando eu rodei a mesma conta no
   navegador, em cima do que estava desenhado na tela. Por isso agora toda cor de texto e medida
   contra os TRES fundos que o app usa.
"""

from __future__ import annotations

import re
from pathlib import Path

ESTATICOS = Path(__file__).resolve().parent.parent / "app" / "static"
FOLHA = ESTATICOS / "style.css"
MINIMO = 4.5

TEMAS = [("claro", ":root {"), ("escuro", 'html[data-tema="escuro"] {')]


def _luminancia(cor: str) -> float:
    cor = cor.lstrip("#")
    canais = [int(cor[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    canais = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
    return 0.2126 * canais[0] + 0.7152 * canais[1] + 0.0722 * canais[2]


def _contraste(frente: str, fundo: str) -> float:
    a, b = _luminancia(frente), _luminancia(fundo)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _sobrepor(frente: str, alfa: float, fundo: str) -> str:
    """A cor que o olho ve quando `frente` e desenhada com transparencia por cima de `fundo`."""
    f = [int(frente.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    b = [int(fundo.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(f[i] * alfa + b[i] * (1 - alfa)):02x}" for i in range(3))


def _bloco(nome: str) -> str:
    texto = FOLHA.read_text(encoding="utf-8")
    inicio = texto.index(nome)
    return texto[inicio : texto.index("}", inicio)]


def _tokens(bloco: str) -> dict[str, str]:
    """Os `--nome: #rrggbb` de um bloco do CSS. Le a folha de verdade, nao uma copia no teste.

    Copiar os valores para ca faria o teste continuar verde depois de alguem mudar a paleta, que e
    exatamente o momento em que ele precisa falar.
    """
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", _bloco(bloco)))


def _alfa(bloco: str, token: str) -> float:
    """O alfa escrito no proprio `--x-soft`, em vez de um 0.12 copiado para dentro do teste.

    Se alguem clarear o selo mexendo so no alfa, a conta aqui tem que acompanhar: e a mesma
    mudanca de contraste que trocar a cor, e ninguem lembraria de vir ajustar um numero magico.
    """
    achado = re.search(rf"--{token}-soft:\s*rgba\([^)]*,\s*([\d.]+)\s*\)", _bloco(bloco))
    assert achado is not None, f"--{token}-soft nao existe ou nao e rgba no bloco {bloco}"
    return float(achado.group(1))


# Toda cor que vira TEXTO em algum lugar do app.
CORES_DE_TEXTO = ["text", "muted", "accent", "ok", "warn", "danger", "erro-texto", "roxo"]
# Prata e bronze sao o 2o e o 3o lugar do ranking: numero pequeno, e a unica marca de posicao.
CORES_DE_TEXTO += ["prata", "bronze"]
# Os tres fundos que existem: a pagina, o card, e o fundo de botao e campo. Uma cor de texto pode
# cair em qualquer um dos tres, entao ela precisa passar nos tres.
FUNDOS = ["bg", "surface", "surface-2"]
# Cores que viram texto em cima de si mesmas lavadas, que e como os selos sao desenhados.
SELOS = ["ok", "warn", "accent", "danger"]


def test_texto_tem_contraste_nos_dois_temas():
    for tema, bloco in TEMAS:
        cores = _tokens(bloco)
        for frente in CORES_DE_TEXTO:
            for fundo in FUNDOS:
                razao = _contraste(cores[frente], cores[fundo])
                assert razao >= MINIMO, (
                    f"{tema}: --{frente} sobre --{fundo} da {razao:.2f}, precisa de {MINIMO}"
                )


def test_selos_sao_legiveis_sobre_o_proprio_fundo_lavado():
    """O caso que passou despercebido: o selo e a cor cheia sobre a mesma cor lavada.

    Um selo de 11px em maiusculas com 3.25 de contraste e desenho, nao texto. E o "concluido" do
    dashboard e do quadro, que e a informacao que a pessoa mais procura na tela.
    """
    for tema, bloco in TEMAS:
        cores = _tokens(bloco)
        for token in SELOS:
            fundo = _sobrepor(cores[token], _alfa(bloco, token), cores["surface"])
            razao = _contraste(cores[token], fundo)
            assert razao >= MINIMO, (
                f"{tema}: selo --{token} sobre {fundo} da {razao:.2f}, precisa de {MINIMO}"
            )


def test_texto_em_cima_do_azul_cheio_e_legivel():
    """O botao primario e o unico lugar onde o fundo e o proprio --accent.

    `--sobre-accent` existe so para isso, e e facil alguem "simplificar" trocando por branco fixo:
    no tema escuro o azul e claro, e branco em cima dele da 2.4.
    """
    for tema, bloco in TEMAS:
        cores = _tokens(bloco)
        razao = _contraste(cores["sobre-accent"], cores["accent"])
        assert razao >= MINIMO, (
            f"{tema}: --sobre-accent sobre --accent da {razao:.2f}, precisa de {MINIMO}"
        )


def _tintas_da_marca(tema: str) -> set[str]:
    """As duas cores chapadas do PNG da marca daquele tema, lidas do arquivo.

    So os pixels cheios contam: a borda das letras e mistura com o vazio, e as duas mais comuns sao
    as duas palavras. O resto e antiserrilhado.
    """
    from collections import Counter

    from PIL import Image

    arte = Image.open(ESTATICOS / f"marca-no-{tema}.png").convert("RGBA")
    cheios = Counter(cor[:3] for cor in arte.get_flattened_data() if cor[3] == 255)
    return {f"#{r:02x}{g:02x}{b:02x}" for (r, g, b), _ in cheios.most_common(2)}


def test_a_marca_de_cada_tema_usa_as_cores_daquele_tema():
    """O PNG da marca e o unico lugar do app onde uma cor do tema mora FORA do style.css.

    Ela e desenhada pelo scripts/arte.py, que tem os valores copiados para dentro dele porque PNG
    nao le variavel de CSS. Copia sem amarra e copia que envelhece: alguem ajusta a paleta na folha,
    ninguem lembra do script, e a marca fica com o azul velho num app de azul novo. Ou pior, com o
    azul de um tema no fundo do outro, onde ela simplesmente some.

    Conferir por IGUALDADE e nao por contraste e o que fecha isso. `--accent` e `--text` ja passam
    pelo teste de contraste contra `--bg` la em cima, entao provar que a marca usa exatamente esses
    dois valores prova de tabela que ela le nos dois temas, sem repetir a conta aqui.
    """
    for tema, bloco in TEMAS:
        cores = _tokens(bloco)
        # O "subido" leva o azul da interface e o "CLÃ" leva a cor do texto: as mesmas duas funcoes
        # que as duas palavras tem no desenho original.
        esperado = {cores["accent"], cores["text"]}
        assert _tintas_da_marca(tema) == esperado, (
            f"{tema}: a marca esta em {_tintas_da_marca(tema)} e o CSS pede {esperado}. "
            "Rode `python scripts/arte.py` depois de mexer na paleta."
        )


def test_cada_tema_esconde_a_marca_do_outro():
    """As duas marcas vao no HTML sempre; quem escolhe uma e o CSS.

    Sem estas duas regras as DUAS aparecem, uma embaixo da outra, e a do tema errado e justamente a
    que some no fundo: o resultado e um espaco vazio do tamanho da marca em cima da assinatura. E um
    defeito que passa em qualquer teste que so olhe o HTML, porque o HTML esta certo.
    """
    regras = re.sub(r"/\*.*?\*/", "", FOLHA.read_text(encoding="utf-8"), flags=re.S)
    regras = re.sub(r"\s+", " ", regras)
    for tema, escondida in [("claro", "escuro"), ("escuro", "claro")]:
        assert f'html[data-tema="{tema}"] .marca-no-{escondida}' in regras, (
            f"o tema {tema} nao esconde a marca do {escondida}: as duas vao aparecer juntas"
        )


def test_o_texto_de_leitor_de_tela_nao_some_do_leitor():
    """`.so-leitor` tem que sair da tela SEM sair da arvore de acessibilidade.

    E a diferenca inteira entre a classe funcionar e ela ser um jeito rebuscado de escrever
    `display: none`. Quem for "limpar" essa regra um dia vai olhar para sete propriedades esquisitas
    e pensar em trocar tudo por uma linha; nesse dia o unico nome que o botao de tema tem desaparece,
    a tela continua identica, e ninguem percebe. Este teste e o que fala nessa hora.
    """
    regra = _bloco(".so-leitor {")
    for jeito_errado in ("display: none", "visibility: hidden"):
        assert jeito_errado not in regra, (
            f".so-leitor usa {jeito_errado}, que tira o texto tambem do leitor de tela"
        )
    assert "clip-path" in regra, ".so-leitor precisa sumir por recorte para continuar no leitor"


def test_o_laranja_antigo_nao_voltou():
    # O #ff6b35 era a cor do Copy e Cola. Ele saiu junto com o nome, e nenhuma regra nova pode
    # traze-lo de volta por copiar e colar de um trecho antigo da folha.
    regras = re.sub(r"/\*.*?\*/", "", FOLHA.read_text(encoding="utf-8"), flags=re.S)
    assert "#ff6b35" not in regras.lower()
