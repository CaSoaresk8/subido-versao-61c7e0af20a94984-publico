"""O cla: criar um, convidar para dentro dele, entrar por convite e trocar de cla ativo.

As duas rotas publicas daqui sao as duas unicas portas do app, e cada uma diz em qual cla a pessoa
vai cair: `/criar-cla` abre um cla novo (quem abriu e o primeiro membro) e `/convite/{token}` entra
num cla que ja existe. Nao ha porta que adivinhe destino.

O resto exige login e roda no cla ativo, como qualquer outra tela: qualquer membro gera convite,
lista os convites do proprio cla e revoga, porque o cla foi pedido sem lider.
"""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import abrir_sessao, escopo_logado, escopo_opcional, templates
from app.escopo import EscopoCla
from app.models import Convite, Membro
from app.repositorios import contas as repo_contas
from app.repositorios import convites as repo_convites
from app.repositorios import membros as repo_membros
from app.servicos import contas as servico_contas
from app.servicos import convites as servico_convites
from app.servicos import limites
from app.servicos import logos as servico_logos
from app.servicos.erros import NaoEncontrado

router = APIRouter()


def _link_base(request: Request) -> str:
    """De onde o link de convite sai, para quem convida poder copiar e colar em qualquer lugar.

    Vem do pedido e nao de configuracao: o app responde em cla.ialabor.com em producao e em
    localhost no dev, e um endereco fixo no config daria link que nao abre no dev.
    """
    return str(request.base_url).rstrip("/")


@router.get("/cla")
def ver_cla(
    request: Request,
    escopo: EscopoCla = Depends(escopo_logado),
):
    convites = repo_convites.do_cla(escopo)
    from app.servicos.agenda import e_dono_da_plataforma

    return templates.TemplateResponse(
        request,
        "cla.html",
        {
            "membro": escopo.membro,
            "membros": repo_membros.todos(escopo),
            "convites": convites,
            # O servico e quem sabe se um convite ainda serve; a tela so pinta. Sem isto o template
            # teria que repetir as quatro condicoes de validade em Jinja.
            "vale": {c.id: servico_convites.vale(c) for c in convites},
            "situacoes": {c.id: servico_convites.situacao(c) for c in convites},
            "validades": servico_convites.VALIDADES,
            "validade_padrao": servico_convites.VALIDADE_PADRAO,
            "link_base": _link_base(request),
            "erro": request.query_params.get("erro"),
            "gerado": request.query_params.get("gerado"),
            # O atalho para a tela de rastreadores aparece so para quem pode abri-la. Mostrar um
            # link que responde 404 seria pior do que nao mostrar nada.
            "e_dono": e_dono_da_plataforma(escopo.membro.usuario),
        },
    )


@router.post("/cla/convites")
def gerar_convite(
    dias: int = Form(servico_convites.VALIDADE_PADRAO),
    max_usos: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    # Campo vazio e "sem limite de usos". Texto que nao e numero vira None em vez de estourar: o
    # formulario e `type=number`, mas quem manda o POST nao e obrigado a ser o formulario.
    limite = int(max_usos) if max_usos.strip().isdigit() else None

    problema = servico_convites.validar_pedido(dias, limite)
    if problema:
        return RedirectResponse(f"/cla?erro={problema}", status_code=303)

    convite = servico_convites.gerar(escopo, dias=dias, max_usos=limite)
    escopo.db.commit()
    # O id do convite novo volta na URL para a tela poder destacar qual acabou de sair, entre
    # varios que podem estar valendo ao mesmo tempo.
    return RedirectResponse(f"/cla?gerado={convite.id}", status_code=303)


@router.post("/cla/convites/{convite_id}/revogar")
def revogar_convite(
    convite_id: int,
    escopo: EscopoCla = Depends(escopo_logado),
):
    convite = repo_convites.por_id(escopo, convite_id)
    if convite is None:
        # Convite de outro cla e convite que nao existe dao o mesmo 404. Um 403 aqui confirmaria
        # que o id existe em algum lugar, que e exatamente o que nao se quer contar.
        raise NaoEncontrado("Convite não encontrado")
    servico_convites.revogar(escopo, convite)
    escopo.db.commit()
    return RedirectResponse("/cla", status_code=303)


@router.post("/cla/logo")
def trocar_logo(
    logo: UploadFile | None = File(None),
    remover: str = Form(""),
    escopo: EscopoCla = Depends(escopo_logado),
):
    """Poe, troca ou tira o logo do cla ativo. Qualquer membro pode, como tudo mais aqui.

    Existe separado de `/criar-cla` porque o cla que ja esta em producao nasceu antes do campo, e
    sem esta rota ele nunca teria como ganhar um logo: a unica porta que aceita arquivo e a de
    criar, e ninguem vai recriar um cla com 17 pessoas dentro para trocar uma imagem.
    """
    cla = escopo.cla
    if remover:
        if cla.logo:
            servico_logos.apagar(cla.logo)
            cla.logo = None
            escopo.db.commit()
        return RedirectResponse("/cla", status_code=303)

    if logo is None or not logo.filename:
        return RedirectResponse("/cla?erro=Escolha um arquivo de imagem.", status_code=303)
    try:
        imagem = servico_logos.conferir(logo.file.read())
    except servico_logos.LogoInvalido as recusa:
        # Sem quote na mao: o RedirectResponse ja escapa o Location, e o resto do arquivo manda
        # mensagem por `?erro=` do mesmo jeito.
        return RedirectResponse(f"/cla?erro={recusa}", status_code=303)

    cla.logo = servico_logos.gravar(imagem, cla.id, anterior=cla.logo)
    escopo.db.commit()
    return RedirectResponse("/cla", status_code=303)


@router.post("/cla/ativo")
def trocar_cla(
    request: Request,
    cla_id: int = Form(...),
    escopo: EscopoCla = Depends(escopo_logado),
):
    """Troca o cla que a sessao esta olhando. O cla anterior continua existindo e editavel.

    A participacao e reconferida no banco antes de a sessao mudar: sem isso, este POST seria um
    jeito de entrar em qualquer cla escrevendo o id na mao, e o cookie passaria a valer como
    autorizacao. Cla do qual a pessoa nao participa da 404, igual a cla que nao existe.
    """
    destino = repo_contas.membro_do_usuario_no_cla(escopo.db, escopo.membro.usuario_id, cla_id)
    if destino is None:
        raise NaoEncontrado("Clã não encontrado")
    abrir_sessao(request, destino)
    return RedirectResponse("/", status_code=303)


@router.get("/criar-cla")
def tela_criar_cla(
    request: Request,
    escopo: EscopoCla | None = Depends(escopo_opcional),
):
    return templates.TemplateResponse(
        request,
        "criar_cla.html",
        # `membro` e o nome que base.html espera: com ele a pagina ganha o cabecalho de quem ja
        # esta logado (e o caminho de volta para o cla atual), e sem ele fica a tela limpa de quem
        # chegou de fora. Uma chave, os dois estados.
        {"erro": None, "dados": {}, "membro": escopo.membro if escopo else None},
    )


@router.post("/criar-cla")
def criar_cla(
    request: Request,
    nome_cla: str = Form(...),
    nome: str = Form(""),
    email: str = Form(""),
    senha: str = Form(""),
    telefone: str = Form(""),
    logo: UploadFile | None = File(None),
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
):
    """Abre um cla. Se ja tem alguem logado, usa a conta dela; se nao, cria a conta junto.

    E a unica porta do app que nao depende de convite, e e ela que faz "outros clas podem usar"
    existir: sem isto, um grupo de fora nunca teria como comecar, porque conta nova so vem de
    convite e convite so vem de quem ja esta dentro.
    """
    # Conta nova e cla novo sao as duas portas de entrada do app, e as duas escrevem no banco sem
    # ninguem estar logado. Sem teto por IP, um script enche a base de cla e conta de mentira em
    # minutos, e a lista de todo mundo fica suja. Dez por hora passa longe do uso humano: mesmo um
    # escritorio inteiro entrando junto, com o mesmo IP, nao chega perto.
    ip = limites.de_onde(request)
    espera = limites.cadastro.bloqueado(ip)
    if espera:
        return templates.TemplateResponse(
            request,
            "criar_cla.html",
            {
                "erro": f"Muitos cadastros deste endereço. Tente de novo em {limites.em_minutos(espera)}.",
                "dados": {},
                "membro": escopo.membro if escopo else None,
            },
            status_code=429,
        )
    # Conta a tentativa, e nao o sucesso: quem tenta mil vezes com dado invalido tambem custa
    # trabalho ao servidor, e um robo que erra o formulario continuaria livre.
    limites.cadastro.registrar(ip)

    nome_cla = nome_cla.strip()
    nome, email, telefone = nome.strip(), email.strip().lower(), telefone.strip()
    # `dados` volta para a tela quando algo da errado, e o telefone volta EXATAMENTE como foi
    # digitado, nao normalizado: a pessoa precisa reconhecer no campo o que ela escreveu para achar
    # o proprio erro. Normalizar aqui mostraria um numero que ela nunca digitou.
    dados = {"nome_cla": nome_cla, "nome": nome, "email": email, "telefone": telefone}
    logado = escopo.membro if escopo else None

    def erro(mensagem: str):
        return templates.TemplateResponse(
            request,
            "criar_cla.html",
            {"erro": mensagem, "dados": dados, "membro": logado},
            status_code=400,
        )

    problema = servico_contas.validar_nome_de_cla(nome_cla)
    if problema:
        return erro(problema)

    # O logo e conferido ANTES de qualquer escrita. Ele e o ultimo campo do formulario e o unico
    # que pode falhar por causa do arquivo, e nao do que a pessoa digitou: deixar para depois de
    # criar conta e cla obrigaria a desfazer os dois por causa de um PNG torto.
    imagem = None
    if logo is not None and logo.filename:
        try:
            imagem = servico_logos.conferir(logo.file.read())
        except servico_logos.LogoInvalido as recusa:
            return erro(str(recusa))

    if logado is not None:
        usuario = repo_contas.usuario_por_id(db, logado.usuario_id)
    else:
        problema = servico_contas.validar(db, nome, email, senha, telefone)
        if problema:
            return erro(problema)
        usuario = servico_contas.criar_usuario(db, nome, email, senha, telefone)

    if usuario is None:
        # Sessao apontando para conta que nao existe mais. Nao da para criar cla para ninguem.
        raise NaoEncontrado("Conta não encontrada")

    membro = servico_contas.criar_cla(db, usuario, nome_cla)
    if imagem is not None:
        # So agora o cla tem id, e o id entra no nome do arquivo. O arquivo e gravado antes do
        # commit de proposito: se o commit falhar, sobra um PNG orfao no volume, que nao machuca
        # ninguem. A ordem inversa deixaria o banco apontando para arquivo que nao existe.
        membro.cla.logo = servico_logos.gravar(imagem, membro.cla_id)
    db.commit()
    abrir_sessao(request, membro)
    return RedirectResponse("/", status_code=303)


@router.get("/convite/{token}")
def tela_convite(
    request: Request,
    token: str,
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
):
    convite, recusa = servico_convites.abrir(db, token)
    logado = escopo.membro if escopo else None
    return _pagina_do_convite(request, db, token, convite, recusa, logado, {})


@router.post("/convite/{token}")
def aceitar_convite(
    request: Request,
    token: str,
    nome: str = Form(""),
    email: str = Form(""),
    senha: str = Form(""),
    telefone: str = Form(""),
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
):
    """Entra no cla do token. Sem conta, cria a conta; com conta logada, so cria a participacao.

    A validade e conferida AQUI de novo, e nao so no GET: entre abrir a pagina e clicar no botao o
    convite pode ter sido revogado, vencido ou esgotado por outra pessoa. Conferir so na tela
    deixaria a recusa valendo enquanto a aba estivesse aberta.
    """
    nome, email, telefone = nome.strip(), email.strip().lower(), telefone.strip()
    dados = {"nome": nome, "email": email, "telefone": telefone}
    logado = escopo.membro if escopo else None
    ip = limites.de_onde(request)
    espera = limites.cadastro.bloqueado(ip)
    if espera:
        # O mesmo teto do criar-cla, e o mesmo contador: sao a mesma coisa vista do lado de fora,
        # uma conta nova nascendo. Contadores separados dariam o dobro de tentativas a quem
        # alternasse entre as duas portas.
        convite, _ = servico_convites.abrir(db, token)
        return _pagina_do_convite(
            request,
            db,
            token,
            convite,
            f"Muitos cadastros deste endereço. Tente de novo em {limites.em_minutos(espera)}.",
            logado,
            dados,
        )
    limites.cadastro.registrar(ip)
    convite, recusa = servico_convites.abrir(db, token)
    if recusa:
        return _pagina_do_convite(request, db, token, convite, recusa, logado, dados)

    cla = repo_contas.cla_por_id(db, convite.cla_id)
    if cla is None:
        raise NaoEncontrado("Clã não encontrado")

    if logado is not None:
        usuario = repo_contas.usuario_por_id(db, logado.usuario_id)
    else:
        problema = servico_contas.validar(db, nome, email, senha, telefone)
        if problema:
            return _pagina_do_convite(request, db, token, convite, None, logado, dados, problema)
        usuario = servico_contas.criar_usuario(db, nome, email, senha, telefone)

    if usuario is None:
        raise NaoEncontrado("Conta não encontrada")

    ja_era = repo_contas.membro_do_usuario_no_cla(db, usuario.id, cla.id) is not None
    membro = servico_contas.entrar_no_cla(db, usuario, cla)
    # Quem ja estava dentro nao gasta uso do convite. Um link reaberto por quem ja e membro nao e
    # entrada nova, e contar como uso esgotaria o convite dos outros sem ninguem ter entrado.
    if not ja_era:
        servico_convites.consumir(EscopoCla(db=db, membro=membro), convite)
    db.commit()

    abrir_sessao(request, membro)
    return RedirectResponse("/", status_code=303)


def _pagina_do_convite(
    request: Request,
    db: Session,
    token: str,
    convite: Convite | None,
    recusa: str | None,
    logado: Membro | None,
    dados: dict,
    erro_de_conta: str | None = None,
):
    """A tela do convite, em todos os estados que ela tem.

    Sao tres: o token nao existe (404), o token existe e nao vale mais (400) e o token vale (200,
    com o formulario). Os tres desenham a mesma pagina, e e por isso que a montagem esta num lugar
    so: o GET e o POST recusado precisam responder igual, senao a diferenca entre eles conta algo.

    O nome do cla aparece quando o convite vale, e nao aparece quando ele nao vale. Nao e descuido:
    quem tem um token valido na mao ja foi autorizado a entrar, e precisa saber onde esta entrando;
    quem chegou com um token vencido ou inventado nao recebe nome de cla nenhum.

    A chave do contexto e `cla_do_convite`, e nao `cla`, porque `cla` ja tem dono: o context
    processor de `app/deps.py` poe ali o cla ATIVO da sessao, e o Starlette roda os processors
    depois do contexto da rota (`context.update(...)`), entao o valor deles vence. Com o nome
    repetido, o visitante sem sessao recebia `cla = None` do processor e a tela do convite ficava
    sem o nome do cla justamente no caso que mais precisa dele. Sao duas coisas diferentes: o cla
    que a sessao esta olhando e o cla para onde este token aponta.
    """
    destino = (
        repo_contas.cla_por_id(db, convite.cla_id) if convite is not None and not recusa else None
    )
    codigo = 200
    if recusa:
        codigo = 404 if convite is None else 400
    ja_membro = (
        logado is not None
        and convite is not None
        and repo_contas.membro_do_usuario_no_cla(db, logado.usuario_id, convite.cla_id) is not None
    )
    return templates.TemplateResponse(
        request,
        "convite.html",
        {
            "token": token,
            "cla_do_convite": destino,
            "recusa": recusa,
            "erro": erro_de_conta,
            "dados": dados,
            "membro": logado,
            "ja_membro": ja_membro,
        },
        status_code=codigo,
    )
