"""Quem esta logado, em qual cla, e os globais dos templates.

A sessao guarda `usuario_id` (a conta) e `cla_ativo_id` (em qual cla ela esta olhando agora). Antes
guardava `membro_id`, e cookie antigo continua entrando: a conversao esta em `_da_sessao`, com o
motivo escrito la.
"""

from datetime import date

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import (
    BASE_DIR,
    NOME_DO_APP,
    URL_ZAP,
    VERSAO_CSS,
    VERSAO_ICONE,
    VERSAO_JS,
    VERSAO_MARCA,
    VERSAO_VIDEO,
)
from app.database import get_db
from app.escopo import EscopoCla
from app.models import STATUS_LABEL, Cla, Membro
from app.repositorios import contas as repo_contas


def _cla_da_tela(request: Request) -> dict:
    """Poe o cla ativo e a lista de clas da pessoa em toda pagina, sem cada router passar na mao.

    Era `templates.env.globals["cla_nome"] = CLA_NOME`, um valor fixo lido do ambiente no boot. Nao
    dava para ser global: com varios clas o nome depende de quem esta olhando. O fallback e para as
    telas que rodam sem cla nenhum (login, criar cla, convite), onde o que se nomeia e o app e nao
    um cla.

    `meus_clas` custa uma consulta por pagina renderizada, e e de proposito que ela viva aqui e nao
    em `escopo_opcional`: context processor so roda quando sai template, entao o POST de arrastar
    cartao, que responde JSON, nao paga por um seletor que ninguem vai ver.
    """
    escopo = getattr(request.state, "escopo", None)
    # O rastreador entra aqui pelo mesmo motivo do cla: o base.html precisa saber desenhar o
    # cabecalho de quem nao participa de cla nenhum, sem cada router lembrar de passar.
    rastreador = getattr(request.state, "rastreador", None)
    if escopo is None:
        return {
            "cla": None,
            "cla_nome": NOME_DO_APP,
            "meus_clas": [],
            "rastreador": rastreador,
        }
    return {
        "cla": escopo.cla,
        "cla_nome": escopo.cla.nome,
        "meus_clas": repo_contas.membros_do_usuario(escopo.db, escopo.membro.usuario_id),
        "rastreador": rastreador,
    }


templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates"), context_processors=[_cla_da_tela]
)


def simbolo_do_cla(cla: Cla | None) -> str:
    """O endereco da imagem que representa o cla: o logo dele, ou o icone do app quando nao tem.

    Existe como funcao, e nao como `{{ cla.logo }}` solto no template, porque o banco guarda o NOME
    do arquivo e nao a URL. Montar "/logos/" + nome e decisao da camada web (e o `app.mount` de
    app/main.py que define esse prefixo), e ela precisa estar num lugar so: as duas telas que
    mostram o simbolo, o cabecalho e a pagina do convite, tem que concordar sobre onde ele mora.

    O fallback leva versao pelo mesmo motivo do `<link rel="icon">`: e o mesmo arquivo, e sem o
    numero ele apareceria no cabecalho com a arte antiga que o navegador ja tem guardada. O logo do
    cla nao precisa: o nome dele muda a cada upload, entao o endereco ja muda junto.
    """
    if cla is not None and cla.logo:
        return f"/logos/{cla.logo}"
    return f"/static/icone-192.png?v={VERSAO_ICONE}"


templates.env.globals["simbolo_do_cla"] = simbolo_do_cla
templates.env.globals["status_label"] = STATUS_LABEL
# O nome do PRODUTO, separado de `cla_nome`, que e o nome de quem esta olhando. As duas coisas
# coincidem nas telas sem login, e e justamente por isso que quem precisa do nome do app de verdade
# (a meta de PWA do iOS, que nomeia o icone na tela inicial) nao pode usar `cla_nome`: ela sairia
# com o nome do cla ativo para quem ja esta dentro de um.
templates.env.globals["nome_do_app"] = NOME_DO_APP
templates.env.globals["hoje"] = date.today
templates.env.globals["versao_css"] = VERSAO_CSS
templates.env.globals["versao_js"] = VERSAO_JS
templates.env.globals["versao_marca"] = VERSAO_MARCA
templates.env.globals["versao_icone"] = VERSAO_ICONE
templates.env.globals["versao_video"] = VERSAO_VIDEO
# Global, e nao contexto de router, porque o link de ajuda aparece tanto em tela publica quanto em
# tela logada: passar na mao obrigaria toda rota que desenha cabecalho a lembrar dele.
templates.env.globals["url_zap"] = URL_ZAP

_DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _quando(inicio, duracao_min: int | None = None) -> str:
    """ "qui, 25/09 · 20:00 às 21:00". Escrito aqui e nao com strftime("%a") no template: o %a sai
    no idioma do sistema, e o container do Fly roda em ingles ("Thu")."""
    texto = f"{_DIAS[inicio.weekday()]}, {inicio:%d/%m} · {inicio:%H:%M}"
    if duracao_min:
        from datetime import timedelta

        texto += f" às {inicio + timedelta(minutes=duracao_min):%H:%M}"
    return texto


templates.env.filters["quando"] = _quando


def _agenda_ativa() -> bool:
    from app import config

    return config.AGENDA_ATIVA


# Funcao, e nao valor: o valor seria copiado no boot, e o teste que desliga a agenda nao mudaria o
# menu. Chamada no template, ela le o config na hora de desenhar.
templates.env.globals["agenda_ativa"] = _agenda_ativa


def _da_sessao(request: Request, db: Session) -> Membro | None:
    """O membro que a sessao aponta, ou None. Aceita cookie de antes do multi-cla.

    O cookie em campo das 17 pessoas guarda `membro_id` e nada mais. Recusar esse formato
    derrubaria todo mundo no login sem aviso, num deploy que nao era sobre login. Entao cookie
    antigo e lido uma vez, convertido para o formato novo na propria sessao, e a partir do segundo
    pedido ele ja e um cookie novo.

    O cla_ativo_id do cookie e sempre reconferido contra o banco: se a pessoa nao participa (ou
    deixou de participar) daquele cla, a resposta e None, e nao a linha. Um cookie nao decide em
    qual cla alguem entra.
    """
    usuario_id = request.session.get("usuario_id")
    cla_id = request.session.get("cla_ativo_id")

    if not usuario_id:
        membro_id = request.session.get("membro_id")
        if not membro_id:
            return None
        membro = repo_contas.membro_por_id(db, membro_id)
        if membro is None:
            return None
        request.session["usuario_id"] = membro.usuario_id
        request.session["cla_ativo_id"] = membro.cla_id
        request.session.pop("membro_id", None)
        return membro

    if cla_id:
        membro = repo_contas.membro_do_usuario_no_cla(db, usuario_id, cla_id)
        if membro is not None:
            return membro

    # Sessao sem cla escolhido, ou apontando para cla que a pessoa nao participa mais: cai no
    # primeiro cla dela. Quem nao esta em cla nenhum fica sem escopo, e quem trata isso e o router.
    participacoes = repo_contas.membros_do_usuario(db, usuario_id)
    if not participacoes:
        return None
    request.session["cla_ativo_id"] = participacoes[0].cla_id
    return participacoes[0]


def abrir_sessao(request: Request, membro: Membro) -> None:
    """Guarda a conta e o cla ativo. Duas chaves, porque uma sessao e "quem" mais "olhando o que".

    Mora aqui junto de `_da_sessao`, que le as mesmas duas chaves, porque escrever e ler a sessao
    sao o mesmo contrato visto dos dois lados. Enquanto isso vivia dentro do router de login, cada
    porta nova (criar cla, aceitar convite, trocar de cla) copiava as tres linhas, e a que
    esquecesse o `pop` deixaria o cookie com o formato antigo e o novo ao mesmo tempo.

    `membro_id` do formato antigo sai aqui tambem: quem passa por qualquer porta sai com cookie
    novo, sem depender da conversao em `_da_sessao`.
    """
    request.session["usuario_id"] = membro.usuario_id
    request.session["cla_ativo_id"] = membro.cla_id
    request.session.pop("membro_id", None)


def escopo_opcional(request: Request, db: Session = Depends(get_db)) -> EscopoCla | None:
    membro = _da_sessao(request, db)
    if membro is None:
        return None
    escopo = EscopoCla(db=db, membro=membro)
    # Lido pelo context processor acima, para o cla ativo e o seletor aparecerem em qualquer
    # template sem o router ter que passar nada.
    request.state.escopo = escopo
    return escopo


def rastreador_opcional(request: Request, db: Session = Depends(get_db)):
    """O papel de rastreador da conta logada, se ela tiver.

    Le a mesma chave de sessao que o resto do app (`usuario_id`), e nao uma sessao propria: e a
    mesma pessoa, com um papel a mais. Rastreador que tambem participa de um cla continua tendo o
    cla normalmente; quem nao participa de nenhum entra direto no painel.
    """
    from app.repositorios import rastreadores as repo_rastreadores

    usuario_id = request.session.get("usuario_id")
    if not usuario_id:
        return None
    rastreador = repo_rastreadores.por_usuario(db, usuario_id)
    # Lido pelo base.html para desenhar o cabecalho de quem nao tem cla.
    request.state.rastreador = rastreador
    return rastreador


def rastreador_logado(rastreador=Depends(rastreador_opcional)):
    if rastreador is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return rastreador


def escopo_logado(escopo: EscopoCla | None = Depends(escopo_opcional)) -> EscopoCla:
    if escopo is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return escopo


def membro_opcional(escopo: EscopoCla | None = Depends(escopo_opcional)) -> Membro | None:
    """Para as telas publicas, que precisam saber se ja tem alguem logado e mais nada.

    O par `membro_logado` nao existe mais: toda rota que exige login precisa do escopo inteiro
    para consultar qualquer coisa, e devolver so o Membro era um jeito de escrever consulta sem
    cla. Quem precisa do membro pega `escopo.membro`.
    """
    return escopo.membro if escopo else None


def central_ativa():
    import os

    return os.environ.get("CENTRAL_ATIVA", "1") == "1"


templates.env.globals["central_ativa"] = central_ativa
