"""Deriva os arquivos de imagem do app a partir da arte original em `arte/`.

Roda so quando a arte muda:  uv run python scripts/arte.py

Os originais ficam versionados em `arte/` de proposito. Sem eles, os PNGs de `app/static/` seriam
binarios sem procedencia: ninguem saberia de onde sairam nem como refazer um tamanho novo. Com eles
mais este script, todo arquivo gerado tem receita.

Substitui o antigo scripts/icones.py, que DESENHAVA o icone em PNG puro porque nao havia arte. Agora
ha, e redesenhar na mao um logo que existe seria fazer uma copia pior dele.

Sai daqui:

- icone-192 / icone-512      o icone do app, quadrado, ja com o fundo azul da arte. Icone PRECISA de
                             fundo proprio: o Android e o iOS desenham ele em cima do papel de
                             parede de quem instalou, que pode ser qualquer coisa.
- icone-mascara-512          o mesmo com folga nas bordas. O Android recorta o icone na forma que
                             o aparelho usa (circulo, quadrado arredondado, gota), e o que fica
                             fora da area segura some. Sem a folga, o til do CLA e cortado.
- marca-no-claro.png         a assinatura "subidoCLA" sem fundo nenhum, para a tela clara.
- marca-no-escuro.png        a mesma, nas cores da tela escura.

Por que DUAS marcas e nao uma. A assinatura e de duas cores: "subido" claro e "CLA" escuro. Isso so
se sustenta sobre o azul do arquivo original, e o azul e justamente o que nao pode aparecer na
pagina: um retangulo azul no meio da tela nao e a marca integrada ao fundo, e um adesivo colado por
cima dele. Sem o azul, uma cor sempre some: o "subido" branco no tema claro, o "CLA" preto no
escuro. Entao o fundo sai, e cada palavra recebe a cor que o tema da pagina ja usa para a mesma
funcao: o azul da interface no "subido", a cor do texto no "CLA". A assinatura continua de duas
cores, e as duas continuam legiveis, que era o ponto do desenho.

Nao da para resolver com um arquivo so e um filtro no CSS: filtro atinge a imagem inteira, e aqui as
duas metades precisam ir para lados diferentes.
"""

from pathlib import Path

from PIL import Image, ImageChops

RAIZ = Path(__file__).resolve().parents[1]
ORIGEM = RAIZ / "arte"
DESTINO = RAIZ / "app" / "static"

# O azul do proprio arquivo, medido e nao escolhido: e a cor de 64% dos pixels do icone.
AZUL = (26, 70, 159)
# Quanto do lado a arte ocupa no icone mascarado. O minimo seguro do Android e 80% do lado, e 78%
# deixa uma margem a mais para o recorte em gota, que e o que mais come as quinas.
AREA_SEGURA = 0.78

# As cores de cada tema, copiadas dos dois blocos de variaveis no topo de app/static/style.css.
# Ficam repetidas aqui porque PNG nao le variavel de CSS, e e por isso que
# tests/test_estilo.py::test_a_marca_de_cada_tema_usa_as_cores_daquele_tema le as tintas do arquivo
# gerado e as compara com estas mesmas variaveis: se alguem mexer na paleta do style.css e esquecer
# deste script, o teste acusa em vez de a marca sumir na tela de alguem.
TEMAS = {
    "marca-no-claro.png": {"subido": (1, 60, 218), "cla": (17, 24, 39)},
    "marca-no-escuro.png": {"subido": (91, 140, 255), "cla": (232, 234, 240)},
}

# Altura do arquivo gerado. O CSS mostra a marca com 64px; 192 e o triplo, que e o que uma tela
# retina pede. Como o desenho vira duas cores chapadas mais o alpha, sair grande custa poucos kB.
ALTURA = 192


def _icone(origem: Image.Image, lado: int) -> Image.Image:
    return origem.convert("RGB").resize((lado, lado), Image.LANCZOS)


def _mascarado(origem: Image.Image, lado: int) -> Image.Image:
    arte = origem.convert("RGB").resize((round(lado * AREA_SEGURA),) * 2, Image.LANCZOS)
    tela = Image.new("RGB", (lado, lado), AZUL)
    canto = (lado - arte.width) // 2
    tela.paste(arte, (canto, canto))
    return tela


def _separar(origem: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Devolve as duas mascaras da assinatura: onde esta o "subido" e onde esta o "CLA".

    A separacao e pelo BRILHO, e nao por igualdade de cor, porque a borda de cada letra e uma
    mistura da tinta com o azul do fundo: cortar em "é branco puro" serrilharia o desenho inteiro.
    O fundo tem um brilho no meio do caminho (o azul), a tinta clara vai dele para cima e a escura
    dele para baixo, entao a distancia ate o brilho do fundo ja e, sozinha, a opacidade do pixel.

    Sai como duas mascaras em vez de uma imagem pronta para as cores entrarem depois: assim a
    reducao de tamanho acontece na mascara, em tom de cinza, e nao numa RGBA. Reduzir RGBA mistura
    a cor dos pixels transparentes na borda e deixa um halo em volta das letras.
    """
    cinza = origem.convert("RGB").convert("L")
    fundo = cinza.getpixel((2, 2))

    claro = cinza.point(lambda tom: max(0, min(255, round((tom - fundo) * 255 / (255 - fundo)))))
    escuro = cinza.point(lambda tom: max(0, min(255, round((fundo - tom) * 255 / fundo))))
    return claro, escuro


def _marca(origem: Image.Image, cores: dict, altura: int) -> Image.Image:
    """A assinatura sem fundo, cada palavra na cor que o tema pede.

    O corte e pelo desenho e nao pelo arquivo: a arte vem num quadrado de 1080 com a assinatura numa
    faixa no meio. Sem cortar, o app exibiria um retangulo quase todo vazio e as letras sairiam
    minusculas dentro de qualquer altura que o CSS pedisse.
    """
    claro, escuro = _separar(origem)

    # O recorte sai da soma das duas mascaras, que e exatamente "onde ha desenho".
    recorte = ImageChops.lighter(claro, escuro).getbbox()
    claro, escuro = claro.crop(recorte), escuro.crop(recorte)

    largura = round(claro.width * altura / claro.height)
    tamanho = (largura, altura)
    claro = claro.resize(tamanho, Image.LANCZOS)
    escuro = escuro.resize(tamanho, Image.LANCZOS)

    marca = Image.new("RGBA", tamanho, (0, 0, 0, 0))
    marca.paste(Image.new("RGBA", tamanho, cores["subido"] + (255,)), (0, 0), claro)
    marca.paste(Image.new("RGBA", tamanho, cores["cla"] + (255,)), (0, 0), escuro)
    return marca


def _salvar(imagem: Image.Image, nome: str) -> None:
    caminho = DESTINO / nome
    imagem.save(caminho, "PNG", optimize=True)
    print(f"  {nome:24} {imagem.width}x{imagem.height}  {caminho.stat().st_size} bytes")


if __name__ == "__main__":
    icone = Image.open(ORIGEM / "icone-origem.png")
    assinatura = Image.open(ORIGEM / "assinatura-origem.png")

    _salvar(_icone(icone, 192), "icone-192.png")
    _salvar(_icone(icone, 512), "icone-512.png")
    _salvar(_mascarado(icone, 512), "icone-mascara-512.png")
    for nome, cores in TEMAS.items():
        _salvar(_marca(assinatura, cores, ALTURA), nome)
