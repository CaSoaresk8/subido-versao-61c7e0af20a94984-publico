"""Entrar e sair.

A senha e conferida contra `Usuario`, nao contra `Membro`: a credencial e uma por pessoa, e a
participacao no cla e outra coisa. Por isso o login tem dois passos: descobrir de quem e a conta,
e depois descobrir em qual cla ela vai entrar.

Criar conta nao mora mais aqui. Enquanto existia um cla so, `/criar-conta` podia criar a conta e
por a pessoa dentro dele no mesmo gesto; com varios clas ela teria que adivinhar o destino. As
duas portas de entrada estao em `routers/cla.py`, e cada uma sabe qual e o cla: criar um cla, ou
usar um convite.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import abrir_sessao, membro_opcional, templates
from app.models import Membro
from app.repositorios import contas as repo_contas
from app.security import conferir_senha
from app.servicos import limites

router = APIRouter()


def _destino_seguro(proximo: str) -> str:
    """Para onde ir depois do login: a pagina pedida, ou o dashboard.

    Existe porque o link de convite precisa funcionar para quem JA tem conta: a pagina do convite
    manda para `/login?proximo=/convite/<token>` e o login devolve para la. Sem isto, quem ja tem
    conta nao conseguiria usar um convite, que e exatamente o caso das pessoas que ja estao no app
    e vao ser chamadas para um segundo cla.

    So passa caminho do proprio app. `//outro.site` e recusado porque o navegador le `//` como
    endereco absoluto: aceitar isso faria da tela de login uma ponte para jogar alguem para fora
    logo depois de ter digitado a senha aqui.
    """
    if proximo.startswith("/") and not proximo.startswith(("//", "/\\")):
        return proximo
    return "/"


@router.get("/login")
def tela_login(
    request: Request,
    proximo: str = "",
    membro: Membro | None = Depends(membro_opcional),
):
    destino = _destino_seguro(proximo)
    if membro:
        return RedirectResponse(destino, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"erro": None, "proximo": destino})


@router.post("/login")
def entrar(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
    proximo: str = Form("/"),
    db: Session = Depends(get_db),
):
    destino = _destino_seguro(proximo)

    def erro(mensagem: str, codigo: int = 401):
        return templates.TemplateResponse(
            request, "login.html", {"erro": mensagem, "proximo": destino}, status_code=codigo
        )

    # A chave junta IP e email: por IP so, um escritorio inteiro se bloquearia junto; por email so,
    # bastaria trocar de email para continuar testando senha de gente do mesmo lugar.
    chave = f"{limites.de_onde(request)}|{email.strip().lower()}"
    espera = limites.senha.bloqueado(chave)
    if espera:
        # 429, e nao 401: nao e a senha que esta errada agora, e o numero de tentativas.
        return erro(f"Tentativas demais. Espere {limites.em_minutos(espera)} e tente de novo.", 429)

    usuario = repo_contas.usuario_por_email(db, email)
    # Conta que nao existe e senha errada dao a MESMA resposta, e de proposito. Dizer "esse email
    # nao esta cadastrado" e confirmar quem tem conta aqui para quem estiver testando emails.
    if usuario is None or not conferir_senha(senha, usuario.senha_hash):
        castigo = limites.senha.registrar(chave)
        if castigo:
            return erro(
                f"Tentativas demais. Espere {limites.em_minutos(castigo)} e tente de novo.", 429
            )
        return erro("Email ou senha incorretos.")

    limites.senha.limpar(chave)
    participacoes = repo_contas.membros_do_usuario(db, usuario.id)
    if not participacoes:
        # Rastreador pode nao participar de cla nenhum: o papel dele e de plataforma. Sem isto, a
        # pessoa contratada pela mentoria entraria com a senha certa e seria mandada para a tela de
        # "crie um cla", que e o oposto do que ela veio fazer.
        from app.repositorios import rastreadores as repo_rastreadores

        if repo_rastreadores.por_usuario(db, usuario.id) is not None:
            request.session["usuario_id"] = usuario.id
            request.session.pop("cla_ativo_id", None)
            return RedirectResponse("/rastreador", status_code=303)
        # A senha estava certa: a conta existe e e dela. O que falta e cla, e cla nao se adivinha.
        # As duas saidas sao caminho de verdade: o convite de quem chamou, ou abrir um cla proprio.
        return erro(
            "Sua conta não está em nenhum clã. Use o link de convite de quem te chamou, "
            "ou crie um clã novo."
        )

    abrir_sessao(request, participacoes[0])
    return RedirectResponse(destino, status_code=303)


@router.post("/sair")
def sair(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
