import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import v1 as api_v1
from app.config import BASE_DIR, PRODUCAO, SECRET_KEY
from app.deps import templates
from app.esquema import atualizar as atualizar_esquema
from app.esquema import backup_diario
from app.routers import (
    acompanhamento,
    central_fluxo,
    demonstracao,
    aulas_ia,
    versoes,
    agenda,
    legal,
    auth,
    cla,
    colunas,
    dashboard,
    historico,
    missoes,
    quadro,
    rastreador,
    tarefas,
    tutorial,
)
from app.sessao import SessaoEmCookie
from app.servicos.erros import DestinoInvalido, ForaDeRegra, NaoEncontrado
from app.servicos import limites
from app.servicos.logos import PASTA as PASTA_LOGOS

# O schema e do Alembic e de mais ninguem. Se uma revisao falhar, o app nao sobe, o health check
# nao passa e o Fly nao promove a versao quebrada. E o comportamento que se quer.
atualizar_esquema()

ESTATICO = BASE_DIR / "static"

log = logging.getLogger(__name__)

# De quanto em quanto tempo o app confere se ja fez o backup do dia. Doze horas, e nao vinte e
# quatro: a maquina pode reiniciar a qualquer hora, e com a janela menor o dia nao passa em branco
# quando o reinicio cai perto da virada. `backup_diario` ja recusa fazer duas copias no mesmo dia.
INTERVALO_BACKUP = 12 * 60 * 60


async def _backup_periodico() -> None:
    """O backup diario, rodando dentro do proprio app.

    Nao e um cron externo porque o volume do SQLite so pode estar montado em UMA maquina, que e
    esta: uma maquina agendada separada nao conseguiria nem abrir o banco. Roda em thread para nao
    segurar o laço de eventos enquanto o SQLite copia.
    """
    while True:
        try:
            feito = await asyncio.to_thread(backup_diario)
            if feito is not None:
                log.warning("backup diario do banco: %s", feito.name)
        except Exception:  # noqa: BLE001
            # Backup que falha nao pode derrubar o app: ele existe para o caso ruim, e virar o caso
            # ruim seria o contrario do objetivo. Fica no log, e o deploy seguinte tenta de novo.
            log.exception("falha no backup diario")
        await asyncio.sleep(INTERVALO_BACKUP)


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI) -> AsyncIterator[None]:
    tarefa = asyncio.create_task(_backup_periodico())
    from app.servicos.central.fluxo import executar_fila

    fila = asyncio.create_task(executar_fila())
    try:
        yield
    finally:
        fila.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await fila
        tarefa.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarefa


app = FastAPI(title="Copy e Cola", lifespan=ciclo_de_vida)
# https_only fica desligado no dev porque ali o app roda em http e o cookie nem seria enviado.
app.add_middleware(
    SessaoEmCookie,
    secret_key=SECRET_KEY,
    max_age=60 * 60 * 24 * 30,
    https_only=PRODUCAO,
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=str(ESTATICO)), name="static")
# Os logos NAO moram em /static: static vive dentro da imagem e some no deploy seguinte. Estes sao
# arquivos que os clas mandaram, entao ficam no volume (DATA_DIR) e ganham rota propria.
app.mount("/logos", StaticFiles(directory=str(PASTA_LOGOS)), name="logos")


# Os dois precisam sair da raiz: o service worker so controla o que esta no escopo dele.
# E os dois saem com no-cache, que nao quer dizer "nao guarde" e sim "pergunte antes de usar". Sao
# os dois arquivos que ENSINAM o resto: o manifesto diz qual icone o app instalado usa, o sw diz o
# que fica guardado para o offline. Servidos sem revalidar, um deploy fica invisivel para quem ja
# abriu o app uma vez, e o sintoma nao parece cache: parece que o deploy nao subiu.
SEM_GUARDAR = {"Cache-Control": "no-cache"}

# O tutorial tem 22 MB e e servido sem login, porque e ele que explica o app para quem ainda nao
# entrou. Isso o torna o pedido mais caro do app: um laco de download consome banda paga e deixa a
# maquina (uma so) lenta para quem esta usando. Quem assiste de verdade baixa uma vez, e o navegador
# guarda; o teto so existe para o laco.
ARQUIVO_PESADO = "/static/tutorial.mp4"


@app.middleware("http")
async def limitar_arquivo_pesado(request: Request, chamar_proximo):
    if request.url.path == ARQUIVO_PESADO:
        ip = limites.de_onde(request)
        espera = limites.video.bloqueado(ip) or limites.video.registrar(ip)
        if espera:
            # 429 com Retry-After: cliente educado respeita, e o player mostra erro em vez de
            # ficar tentando. O texto e curto porque quem le isto e um script, nao uma pessoa.
            return PlainTextResponse(
                "Muitos downloads deste vídeo. Tente mais tarde.",
                status_code=429,
                headers={"Retry-After": str(espera)},
            )
    return await chamar_proximo(request)


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifesto(request: Request):
    # Template, e nao arquivo parado: os enderecos dos icones precisam levar `?v=`. O porque esta
    # escrito dentro do proprio app/templates/manifest.webmanifest.
    return templates.TemplateResponse(
        request,
        "manifest.webmanifest",
        media_type="application/manifest+json",
        headers=SEM_GUARDAR,
    )


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        ESTATICO / "sw.js", media_type="application/javascript", headers=SEM_GUARDAR
    )


# A API vem ANTES das telas. Na fase 5 o React ganha um catch-all em /app/{path}, e catch-all
# registrado antes de /api/v1 engoliria a API inteira. A ordem aqui e o que impede isso, e ela so e
# obvia enquanto o catch-all nao existe.
app.include_router(api_v1.router)

app.include_router(auth.router)
app.include_router(cla.router)
app.include_router(dashboard.router)
app.include_router(missoes.router)
app.include_router(agenda.router)
app.include_router(acompanhamento.router)
app.include_router(aulas_ia.router)
app.include_router(central_fluxo.router)
app.include_router(demonstracao.router)
app.include_router(versoes.router)
app.include_router(quadro.router)
app.include_router(tarefas.router)
app.include_router(colunas.router)
app.include_router(historico.router)
app.include_router(tutorial.router)
app.include_router(legal.router)
app.include_router(rastreador.router)


@app.exception_handler(StarletteHTTPException)
async def redirecionar_nao_logado(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    return await http_exception_handler(request, exc)


# Aqui, e so aqui, regra de negocio vira codigo de resposta. O corpo e {"detail": ...} igual ao da
# HTTPException para que trocar o raise dentro do servico nao mude o que o navegador recebe.
@app.exception_handler(NaoEncontrado)
async def nao_encontrado(request: Request, exc: NaoEncontrado):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(DestinoInvalido)
async def destino_invalido(request: Request, exc: DestinoInvalido):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(ForaDeRegra)
async def fora_de_regra(request: Request, exc: ForaDeRegra):
    """400: o pedido chegou completo e mesmo assim nao pode.

    A mensagem do servico atravessa inteira, porque ela foi escrita para uma pessoa ler ("O quadro
    aceita no máximo 8 colunas suas."). As rotas de HTML continuam pegando a excecao na mao, porque
    elas nao respondem JSON: redesenham o formulario ou voltam para o quadro com `?erro=`.
    """
    return JSONResponse({"detail": str(exc)}, status_code=400)
