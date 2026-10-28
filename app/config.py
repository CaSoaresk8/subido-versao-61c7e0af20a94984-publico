import os
from pathlib import Path
from urllib.parse import quote

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'copyecola.db'}")

CHAVE_DE_MENTIRA = "dev-inseguro-trocar-em-producao"
SECRET_KEY = os.getenv("SECRET_KEY", CHAVE_DE_MENTIRA)
PRODUCAO = os.getenv("PRODUCAO") == "1"

# O cookie de sessao e apenas assinado com essa chave. Com a chave padrao, que esta aqui no
# codigo, qualquer um forja o cookie de qualquer membro. Em producao a app recusa subir.
if PRODUCAO and SECRET_KEY == CHAVE_DE_MENTIRA:
    raise RuntimeError("Defina SECRET_KEY: sem ela qualquer um entra como qualquer membro.")

# O nome do PRODUTO, que e outra coisa do nome do cla. Era CLA_NOME, uma variavel de ambiente que
# servia para os dois porque existia um cla so. Agora o nome do cla mora na tabela `cla` e muda
# conforme quem esta olhando; isto aqui e o que aparece para quem ainda nao esta em cla nenhum:
# login, criar cla e a pagina do convite. Nao vem do ambiente porque nao e configuracao de
# instalacao: e o nome do app, igual para todos os clas que ele hospeda.
# "Copy e Cola" saiu daqui por isso: aquilo e o nome de UM cla, o que esta em producao, e ele
# continua se chamando assim pela linha dele na tabela `cla`. Quem criar outro escolhe o proprio.
NOME_DO_APP = "Subido Clã"

# O WhatsApp de quem cuida do app. Aparece em cinco telas (o botao redondo do cabecalho e o link
# discreto do login, do criar cla, do convite e do tutorial), e por isso mora aqui e nao escrito
# dentro de cada template: trocar de numero com ele copiado em cinco lugares e trocar em quatro e
# descobrir o quinto pela mensagem que chegou no telefone errado.
# Nao vem do ambiente porque nao e segredo nem configuracao de instalacao: e um numero publico, feito
# para ser clicado, e o mesmo em qualquer lugar onde este app subir.
ZAP_SUPORTE = "5511976012274"
# O texto ja vem escrito na conversa. Sem ele chega um "oi" sem contexto, e do outro lado nao da para
# saber de qual das telas a pessoa veio nem do que ela esta falando.
URL_ZAP = f"https://wa.me/{ZAP_SUPORTE}?text={quote(f'Olá! É sobre o {NOME_DO_APP}: ')}"


def _versao(*nomes: str) -> str:
    """O instante da ultima gravacao entre os arquivos dados, em segundos inteiros.

    Aceita mais de um nome porque a marca sao dois arquivos gerados no mesmo passo. Pegar o maior
    e o que garante que o endereco muda mesmo quando so um deles e regravado.
    """
    return str(max(int((BASE_DIR / "static" / nome).stat().st_mtime) for nome in nomes))


# O StaticFiles nao manda Cache-Control, entao o navegador decide sozinho por quanto tempo guarda o
# css. Depois de um deploy isso servia a folha antiga com as regras novas faltando. O numero no fim
# do endereco muda quando o arquivo muda, e ai o navegador e obrigado a buscar de novo.
VERSAO_CSS = _versao("style.css")
VERSAO_JS = _versao("kanban.js")
# A arte da marca entra na mesma regra, e nao por simetria: ela ja trocou duas vezes, e cada versao
# tinha OUTRA proporcao. Sem o numero no endereco, quem tivesse a antiga no cache do navegador veria
# a arte nova esticada dentro do width/height da antiga, ou pior, continuaria vendo a errada.
# Um numero so para os dois arquivos do tema: eles saem juntos do scripts/arte.py, entao nao existe
# caso real de um mudar sem o outro, e dois numeros seriam dois jeitos de escrever a mesma coisa.
VERSAO_MARCA = _versao("marca-no-claro.png", "marca-no-escuro.png")
# O icone ficou de fora dessa regra e o preco apareceu na hora: o app subiu com a arte nova e a aba
# do navegador continuou mostrando o quadrado laranja do brasao antigo, porque o ARQUIVO mudou e o
# ENDERECO nao. Icone e pior que css nesse ponto. A folha de estilo o navegador ao menos revalida;
# o icone ele guarda em dois lugares que nao sao o cache de HTTP, o banco de favicon e a copia que
# o Chrome tira quando alguem instala o app, e os dois sao indexados pelo endereco. Enquanto o
# endereco for o mesmo, nao existe arte nova: existe a arte que ele ja tinha.
VERSAO_ICONE = _versao("icone-192.png", "icone-512.png", "icone-mascara-512.png")
# O tutorial pela mesma razao, com um agravante: e o arquivo mais pesado do app, 21 MB. Quem ja
# assistiu tem essa gravacao inteira guardada em algum lugar, e sem numero no endereco uma regravacao
# do video simplesmente nao chegaria nessa pessoa. A capa anda junto porque as duas saem do mesmo
# corte: gravacao nova, quadro novo.
VERSAO_VIDEO = _versao("tutorial.mp4", "tutorial-capa.jpg")

# A agenda do cla mora em horario de Brasilia, e a hora de um evento e guardada como hora de PAREDE
# daqui (ver `Evento.inicio`). Nome IANA, e nao "-03:00": o Google Agenda recebe o evento com este
# fuso, e e ele que faz a conta certa para quem abre o convite em outro lugar.
FUSO = "America/Sao_Paulo"

# O app do Google que manda os convites da agenda. Os dois vem do ambiente (`fly secrets`) e nunca do
# codigo. Sem eles a agenda funciona inteira dentro do app e a tela explica que o envio de convite
# ainda nao foi configurado: faltar a integracao nao pode derrubar o resto.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
_GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")


def segredo_google() -> str:
    """O client secret, lido por funcao para nao existir como constante publica importavel.

    Uma constante no modulo aparece em qualquer `repr`/`vars` de quem inspecionar o config, e um
    traceback que imprime as variaveis locais do modulo vazaria o valor. Por funcao, ele so existe
    no instante da troca do codigo pelo token.
    """
    return _GOOGLE_CLIENT_SECRET


GOOGLE_CONFIGURADO = bool(GOOGLE_CLIENT_ID and _GOOGLE_CLIENT_SECRET)

# O endereco publico do app, para o link "No app" dentro do convite do Google. Vem do ambiente
# (fly.toml) porque o convite e montado tambem fora de um pedido HTTP (quando alguem entra no cla),
# onde nao ha `request.base_url` para perguntar. Vazio no dev: o convite so sai sem esse link.
URL_PUBLICA = os.getenv("URL_PUBLICA", "").rstrip("/")

# Quem administra a PLATAFORMA (nao um cla): hoje, so quem conecta e troca a conta Google que manda
# os convites de todos os clas. Lista de emails de login, separados por virgula, vinda do ambiente
# (`fly secrets`), e nao do codigo: e email de pessoa, e nao entra no repositorio.
# Nao e um papel dentro do cla. Os clas continuam sem lider; isto e quem cuida da instalacao.
DONOS_DA_PLATAFORMA = frozenset(
    email.strip().lower()
    for email in os.getenv("DONOS_DA_PLATAFORMA", "").split(",")
    if email.strip()
)

# A agenda do cla (reunioes, workshops, convite pelo Google) pode ficar desligada inteira. Existe
# porque o Caio quis subir o resto antes: o Google so publica o app depois que /privacidade e
# /termos estao no ar, e a agenda depende dessa publicacao. Desligada, as tabelas dela existem
# (vazias) mas nada aparece: menu, paginas, API e calendario agem como se ela nao existisse.
# Lida SEMPRE por `config.AGENDA_ATIVA` na hora do uso, e nunca importada solta, para os testes
# conseguirem desligar sem reiniciar o app.
AGENDA_ATIVA = os.getenv("AGENDA_ATIVA", "1") == "1"
