"""As telas do rastreador: o painel, a escolha de clas e a ficha de cada pessoa.

Tambem moram aqui as duas pontas do papel: o convite que o dono da plataforma gera e a tela onde
alguem aceita esse convite.

Toda rota daqui passa por `rastreador_logado` ou por `_so_dono`. Nenhuma recebe cla pela URL: o
recorte vem sempre da lista de clas que o proprio rastreador escolheu, e id de fora dessa lista
responde 404, igual ao resto do app.
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import escopo_opcional, rastreador_logado, templates
from app.escopo import EscopoCla
from app.models import (
    SITUACOES_DE_MENTORIA,
    STATUS_DO_DIARIO,
    TIPOS_DE_MENTORIA,
    Cla,
    Missao,
    Rastreador,
)
from app.repositorios import diario as repo_diario
from app.repositorios import rastreadores as repo
from app.servicos import mentoria as servico_mentoria
from app.servicos import rastreadores as servico
from app.servicos.agenda import e_dono_da_plataforma, ler_inicio
from app.servicos.erros import FaltaResposta, ForaDeRegra, NaoEncontrado
from app.servicos.missoes import frase_de_falta_de_resposta
from app.servicos.tarefas import data_ou_nada

router = APIRouter()


def _so_dono(escopo: EscopoCla | None) -> None:
    """A tela de rastreadores e do dono da plataforma. Para os outros ela nao existe."""
    if escopo is None or not e_dono_da_plataforma(escopo.membro.usuario):
        raise HTTPException(status_code=404, detail="Página não encontrada")


def _cla_acompanhado(db: Session, rastreador: Rastreador, cla_id: int) -> Cla:
    cla = db.get(Cla, cla_id)
    if cla is None:
        raise HTTPException(status_code=404, detail="Clã não encontrado")
    return cla


# ---------------------------------------------------------------------------------------------
# O painel do rastreador
# ---------------------------------------------------------------------------------------------


@router.get("/rastreador")
def painel(
    request: Request,
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    pessoas = repo.pessoas(db, rastreador)
    return templates.TemplateResponse(
        request,
        "rastreador_painel.html",
        {
            "membro": None,
            "rastreador": rastreador,
            "pessoas": pessoas,
            "clas": repo.clas_acompanhados(db, rastreador),
            # Quem passou uma semana sem tocar no app e o motivo de este painel existir.
            "parados": [p for p in pessoas if p["dias_parado"] >= 7],
        },
    )


@router.get("/rastreador/clas")
def escolher_clas(
    request: Request,
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    meus = repo.ids_dos_clas(db, rastreador)
    return templates.TemplateResponse(
        request,
        "rastreador_clas.html",
        {
            "membro": None,
            "rastreador": rastreador,
            "clas": repo.clas_para_escolher(db),
            "meus": meus,
        },
    )


@router.post("/rastreador/clas/{cla_id}/acompanhar")
def acompanhar(
    cla_id: int,
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    servico.acompanhar(db, rastreador, _cla_acompanhado(db, rastreador, cla_id))
    db.commit()
    return RedirectResponse("/rastreador/clas", status_code=303)


@router.post("/rastreador/clas/{cla_id}/parar")
def parar(
    cla_id: int,
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    servico.parar_de_acompanhar(db, rastreador, _cla_acompanhado(db, rastreador, cla_id))
    db.commit()
    return RedirectResponse("/rastreador/clas", status_code=303)


def _pessoa(db: Session, rastreador: Rastreador, membro_id: int):
    """A pessoa, so se estiver num cla que este rastreador acompanha. Fora disso, o mesmo 404 de
    pessoa que nao existe: trocar o numero da URL nao pode abrir a ficha de ninguem de fora."""
    membro = repo.membro_acompanhado(db, rastreador, membro_id)
    if membro is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    return membro


def _volta(membro_id: int, erro: str | None = None) -> RedirectResponse:
    destino = f"/rastreador/pessoa/{membro_id}"
    if erro:
        destino += "?erro=" + quote(erro)
    return RedirectResponse(destino, status_code=303)


@router.get("/rastreador/pessoa/{membro_id}")
def ficha(
    membro_id: int,
    request: Request,
    erro: str | None = None,
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    pessoa = _pessoa(db, rastreador, membro_id)
    from app.repositorios import entregas as repo_entregas
    from app.repositorios import missoes as repo_missoes

    escopo_da_pessoa = EscopoCla(db=db, membro=pessoa)
    missoes = repo_missoes.ativas(escopo_da_pessoa)
    entregas = repo_entregas.do_membro(escopo_da_pessoa, pessoa.id)
    acompanhamento = repo.acompanhamento_da_pessoa(db, pessoa)
    return templates.TemplateResponse(
        request,
        "rastreador_pessoa.html",
        {
            "membro": None,
            "rastreador": rastreador,
            "pessoa": pessoa,
            "email": repo.email_do_membro(db, pessoa),
            "linhas": [{"missao": m, "entrega": entregas.get(m.id)} for m in missoes],
            # So as tarefas combinadas com a mentoria. As pessoais continuam so da pessoa.
            "tarefas": repo.tarefas_da_mentoria(db, pessoa),
            "saldo": servico_mentoria.saldo(db, pessoa),
            "anotacao": acompanhamento.anotacao if acompanhamento else "",
            "mentorias": repo.mentorias_da_pessoa(db, pessoa),
            # A pessoa tambem pode ajustar o proprio saldo (decisao do Caio). Isto e o que deixa a
            # rastreadora ver quem mudou o que, sem precisar perguntar.
            "historico_do_saldo": repo.historico_do_saldo(db, pessoa),
            # O acompanhamento semanal do cla, so leitura: a mentoria ve o que o cla conversou.
            "perfil": repo_diario.perfil(escopo_da_pessoa, pessoa.id),
            "diario": repo_diario.historico_da_pessoa(escopo_da_pessoa, pessoa.id),
            "status_do_diario": STATUS_DO_DIARIO,
            "tipos_de_mentoria": TIPOS_DE_MENTORIA,
            "situacoes": SITUACOES_DE_MENTORIA,
            "erro": erro,
        },
    )


@router.post("/rastreador/pessoa/{membro_id}/tarefas")
def criar_tarefa(
    membro_id: int,
    titulo: str = Form(""),
    descricao: str = Form(""),
    prazo: str = Form(""),
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    pessoa = _pessoa(db, rastreador, membro_id)
    try:
        servico_mentoria.criar_tarefa(
            db, rastreador, pessoa, titulo, descricao, data_ou_nada(prazo)
        )
    except ForaDeRegra as recusa:
        db.rollback()
        return _volta(membro_id, str(recusa))
    db.commit()
    return _volta(membro_id)


@router.post("/rastreador/pessoa/{membro_id}/tarefas/{tarefa_id}")
def editar_tarefa(
    membro_id: int,
    tarefa_id: int,
    titulo: str = Form(""),
    descricao: str = Form(""),
    prazo: str = Form(""),
    status: str = Form("a_fazer"),
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    pessoa = _pessoa(db, rastreador, membro_id)
    try:
        tarefa = servico_mentoria.tarefa_da_mentoria(db, pessoa, tarefa_id)
        servico_mentoria.editar_tarefa(
            db, rastreador, pessoa, tarefa, titulo, descricao, data_ou_nada(prazo), status
        )
    except NaoEncontrado:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada") from None
    except ForaDeRegra as recusa:
        db.rollback()
        return _volta(membro_id, str(recusa))
    db.commit()
    return _volta(membro_id)


@router.post("/rastreador/pessoa/{membro_id}/missoes/{missao_id}")
def salvar_entrega(
    membro_id: int,
    missao_id: int,
    status: str = Form(...),
    resposta: str = Form(""),
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    pessoa = _pessoa(db, rastreador, membro_id)
    missao = db.get(Missao, missao_id)
    if missao is None or missao.cla_id != pessoa.cla_id:
        raise HTTPException(status_code=404, detail="Missão não encontrada")
    try:
        servico_mentoria.salvar_entrega(db, rastreador, pessoa, missao, status, resposta)
    except FaltaResposta as falta:
        db.rollback()
        return _volta(membro_id, frase_de_falta_de_resposta(falta.missao))
    except (ForaDeRegra, NaoEncontrado) as recusa:
        db.rollback()
        return _volta(membro_id, str(recusa))
    db.commit()
    return _volta(membro_id)


@router.post("/rastreador/pessoa/{membro_id}/saldo")
def ajustar_saldo(
    membro_id: int,
    mensais: int = Form(...),
    livres: int = Form(...),
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    pessoa = _pessoa(db, rastreador, membro_id)
    try:
        servico_mentoria.ajustar_saldo(db, rastreador, pessoa, mensais, livres)
    except ForaDeRegra as recusa:
        db.rollback()
        return _volta(membro_id, str(recusa))
    db.commit()
    return _volta(membro_id)


@router.post("/rastreador/pessoa/{membro_id}/anotacao")
def anotar(
    membro_id: int,
    anotacao: str = Form(""),
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    pessoa = _pessoa(db, rastreador, membro_id)
    servico_mentoria.anotar(db, pessoa, anotacao)
    db.commit()
    return _volta(membro_id)


@router.post("/rastreador/pessoa/{membro_id}/mentorias")
def marcar_mentoria(
    membro_id: int,
    tipo: str = Form(...),
    inicio: str = Form(""),
    duracao_min: int = Form(60),
    local: str = Form(""),
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    pessoa = _pessoa(db, rastreador, membro_id)
    try:
        servico_mentoria.marcar_mentoria(
            db, rastreador, pessoa, tipo, ler_inicio(inicio), duracao_min, local
        )
    except ForaDeRegra as recusa:
        db.rollback()
        return _volta(membro_id, str(recusa))
    db.commit()
    return _volta(membro_id)


@router.post("/rastreador/pessoa/{membro_id}/mentorias/{mentoria_id}")
def atualizar_mentoria(
    membro_id: int,
    mentoria_id: int,
    situacao: str = Form(...),
    anotacao: str = Form(""),
    rastreador: Rastreador = Depends(rastreador_logado),
    db: Session = Depends(get_db),
):
    pessoa = _pessoa(db, rastreador, membro_id)
    try:
        mentoria = servico_mentoria.mentoria_da_pessoa(db, pessoa, mentoria_id)
        servico_mentoria.atualizar_mentoria(db, rastreador, pessoa, mentoria, situacao, anotacao)
    except NaoEncontrado:
        raise HTTPException(status_code=404, detail="Mentoria não encontrada") from None
    except ForaDeRegra as recusa:
        db.rollback()
        return _volta(membro_id, str(recusa))
    db.commit()
    return _volta(membro_id)


# ---------------------------------------------------------------------------------------------
# Convite: o dono gera, a pessoa aceita
# ---------------------------------------------------------------------------------------------


@router.get("/plataforma/rastreadores")
def tela_do_dono(
    request: Request,
    erro: str | None = None,
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
):
    _so_dono(escopo)
    return templates.TemplateResponse(
        request,
        "plataforma_rastreadores.html",
        {
            "membro": escopo.membro,
            "rastreadores": repo.todos(db),
            "convites": repo.convites(db),
            "situacao": servico.situacao,
            "link_base": str(request.base_url).rstrip("/"),
            "erro": erro,
        },
    )


@router.post("/plataforma/rastreadores/convites")
def gerar_convite(
    dias: int = Form(servico.DIAS_PADRAO),
    max_usos: str = Form("1"),
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
):
    _so_dono(escopo)
    try:
        servico.criar_convite(
            db,
            escopo.membro.usuario,
            dias=dias,
            max_usos=int(max_usos) if max_usos.strip().isdigit() else None,
        )
    except ForaDeRegra as recusa:
        return RedirectResponse(f"/plataforma/rastreadores?erro={recusa}", status_code=303)
    db.commit()
    return RedirectResponse("/plataforma/rastreadores", status_code=303)


@router.post("/plataforma/rastreadores/convites/{convite_id}/revogar")
def revogar(
    convite_id: int,
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
):
    _so_dono(escopo)
    from app.models import ConviteRastreador

    convite = db.get(ConviteRastreador, convite_id)
    if convite is None:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    servico.revogar_convite(db, convite)
    db.commit()
    return RedirectResponse("/plataforma/rastreadores", status_code=303)


@router.get("/rastreador/convite/{token}")
def tela_do_convite(
    token: str,
    request: Request,
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
):
    convite = repo.convite_por_token(db, token)
    return templates.TemplateResponse(
        request,
        "convite_rastreador.html",
        {
            "membro": escopo.membro if escopo else None,
            "vale": repo.vale(convite),
            "token": token,
            "dados": {},
            "erro": None,
        },
        status_code=200 if repo.vale(convite) else 400,
    )


@router.post("/rastreador/convite/{token}")
def aceitar(
    token: str,
    request: Request,
    nome: str = Form(""),
    email: str = Form(""),
    senha: str = Form(""),
    telefone: str = Form(""),
    escopo: EscopoCla | None = Depends(escopo_opcional),
    db: Session = Depends(get_db),
):
    dados = {"nome": nome.strip(), "email": email.strip().lower(), "telefone": telefone.strip()}
    try:
        rastreador = servico.aceitar_convite(
            db,
            token,
            nome=dados["nome"],
            email=dados["email"],
            senha=senha,
            telefone=dados["telefone"],
            usuario_logado=escopo.membro.usuario if escopo else None,
        )
    except (ForaDeRegra, NaoEncontrado) as recusa:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "convite_rastreador.html",
            {
                "membro": escopo.membro if escopo else None,
                "vale": isinstance(recusa, ForaDeRegra),
                "token": token,
                "dados": dados,
                "erro": str(recusa),
            },
            status_code=400,
        )
    db.commit()
    # Entra ja logado: quem acabou de virar rastreador nao precisa de mais uma tela de login.
    request.session["usuario_id"] = rastreador.usuario_id
    return RedirectResponse("/rastreador/clas", status_code=303)
