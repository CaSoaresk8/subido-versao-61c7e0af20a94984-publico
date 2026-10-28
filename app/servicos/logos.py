"""O logo do cla: recebe arquivo de quem chegou de fora e grava um PNG que o app mesmo desenhou.

Nada do que chega e servido de volta como chegou, e isso e a regra inteira deste arquivo. O
arquivo e aberto pelo Pillow, decodificado de verdade, redesenhado e gravado num PNG novo com nome
escolhido aqui. Guardar o upload como veio quebraria tres coisas de uma vez:

1. um SVG (ou um HTML com nome de .png) servido de /logos/ roda script na origem do app, com o
   cookie de sessao de quem esta olhando. Decodificar como imagem e o que recusa isso: o Pillow
   nao abre HTML, e o formato aceito e conferido depois de abrir, e nao pelo nome do arquivo;
2. foto de celular carrega EXIF, e EXIF carrega GPS. O logo fica publico para o cla inteiro;
   redesenhar a imagem em outro arquivo deixa os metadados para tras;
3. sem limite de tamanho e de pixel, um upload enche o volume do Fly, que e onde mora o banco.

O nome do arquivo tem sufixo aleatorio de proposito. O endereco do logo vai para o cache do
navegador e para o cache do service worker; com um nome fixo por cla (`cla-3.png`) a troca de logo
nao apareceria para quem ja tinha visto o antigo. Nome novo e endereco novo, e o cache velho deixa
de ser consultado sozinho.

Sobre o nome: na tela isso se chama BRASAO, no codigo continua `logo`. Nao e esquecimento. O nome
visivel e decisao de produto e muda quando o dono quiser; `logo` e coluna de banco, rota
(`/cla/logo`, `/api/v1/clas/atual/logo`) e nome de campo de formulario. Renomear os dois juntos
custaria migracao de schema mais quebra do contrato da API, para nao mudar nada do que a pessoa ve.
Quem vier depois: trocar o texto da tela e seguro, trocar o identificador nao e.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from secrets import token_hex

from PIL import Image, UnidentifiedImageError

from app.config import DATA_DIR

# Fica em DATA_DIR e nao em app/static: em producao DATA_DIR e o volume montado em /data, que
# sobrevive ao deploy. Dentro da imagem, o logo de todo mundo sumiria no proximo `fly deploy`.
PASTA = DATA_DIR / "logos"
PASTA.mkdir(parents=True, exist_ok=True)

LADO = 512
MAXIMO_MB = 4
MAXIMO_BYTES = MAXIMO_MB * 1024 * 1024
FORMATOS = {"PNG", "JPEG", "WEBP"}


class LogoInvalido(ValueError):
    """O arquivo nao vira logo. A mensagem e escrita para a pessoa ler no formulario."""


def conferir(dados: bytes) -> Image.Image:
    """Decodifica o upload e devolve a imagem, ou levanta LogoInvalido com o motivo.

    Separado de `gravar` porque quem chama precisa recusar ANTES de criar cla nenhum: na tela de
    criar cla, um logo torto nao pode deixar meio cla no banco para depois desfazer.
    """
    if not dados:
        raise LogoInvalido("O arquivo do brasão chegou vazio.")
    if len(dados) > MAXIMO_BYTES:
        raise LogoInvalido(f"O brasão precisa ter no máximo {MAXIMO_MB} MB.")
    try:
        imagem = Image.open(BytesIO(dados))
        # open() so le o cabecalho. load() e quem decodifica de verdade, e e aqui que arquivo
        # truncado, arquivo mentindo o formato e bomba de descompressao aparecem.
        imagem.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as falha:
        raise LogoInvalido("Não consegui ler essa imagem. Use PNG, JPG ou WEBP.") from falha
    if imagem.format not in FORMATOS:
        raise LogoInvalido("Envie o brasão em PNG, JPG ou WEBP.")
    return imagem


def gravar(imagem: Image.Image, cla_id: int, anterior: str | None = None) -> str:
    """Grava o PNG do cla e devolve o nome do arquivo. Apaga o logo anterior, se havia um."""
    copia = imagem.convert("RGBA")
    # thumbnail so diminui. Esticar um logo de 80px para 512 nao ganha detalhe nenhum: so gera um
    # arquivo grande e borrado.
    copia.thumbnail((LADO, LADO))
    nome = f"cla-{cla_id}-{token_hex(4)}.png"
    copia.save(PASTA / nome, format="PNG", optimize=True)
    if anterior:
        apagar(anterior)
    return nome


def apagar(nome: str) -> None:
    """Some com o arquivo. `Path(nome).name` porque o que vem do banco nunca vira `../../algo`."""
    (PASTA / Path(nome).name).unlink(missing_ok=True)
