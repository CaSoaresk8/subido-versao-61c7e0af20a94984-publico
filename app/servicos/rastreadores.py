"""Regra do rastreador: o convite que cria o papel, e os clas que ele escolhe acompanhar.

Como nos outros servicos, nada aqui da commit: quem chamou decide se a operacao inteira vale.

Duas regras que sustentam a confianca, e nao sao detalhe de tela:

1. **Ninguem e acompanhado sem saber.** Quando um rastreador passa a acompanhar um cla, isso entra
   no historico DAQUELE cla, com o nome dele. Sair tambem entra.
2. **So o dono da plataforma fabrica rastreador.** O convite e de tabela propria, e a tela que gera
   fica atras da mesma checagem que conecta a conta Google.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Cla, ConviteRastreador, Rastreador, RastreadorCla, Usuario, agora
from app.repositorios import contas as repo_contas
from app.repositorios import rastreadores as repo
from app.servicos import contas as servico_contas
from app.servicos.auditoria import registrar_da_mentoria
from app.servicos.erros import ForaDeRegra, NaoEncontrado

DIAS_PADRAO = 7
DIAS_MAXIMO = 60


def criar_convite(
    db: Session, dono: Usuario, dias: int = DIAS_PADRAO, max_usos: int | None = 1
) -> ConviteRastreador:
    """O link que vira rastreador. Nasce com UM uso por padrao, e nao sem limite como o do cla.

    A diferenca e proposital: o convite de cla chama gente para dentro de um grupo, e circular e o
    objetivo; este da acesso aos dados de varios clas, e um link que circula vira acesso que
    ninguem controla.
    """
    if not 1 <= dias <= DIAS_MAXIMO:
        raise ForaDeRegra(f"A validade vai de 1 a {DIAS_MAXIMO} dias.")
    if max_usos is not None and max_usos < 1:
        raise ForaDeRegra("O limite de usos precisa ser pelo menos 1.")
    convite = ConviteRastreador(
        token=secrets.token_urlsafe(32),
        criado_por_usuario_id=dono.id,
        expira_em=agora() + timedelta(days=dias),
        max_usos=max_usos,
    )
    db.add(convite)
    db.flush()
    return convite


def revogar_convite(db: Session, convite: ConviteRastreador) -> None:
    if convite.revogado_em is None:
        convite.revogado_em = agora()


def situacao(convite: ConviteRastreador) -> str:
    if convite.revogado_em is not None:
        return "Revogado"
    if convite.expira_em < agora():
        return "Vencido"
    if convite.max_usos is not None and convite.usos >= convite.max_usos:
        return "Esgotado"
    return "Válido"


def aceitar_convite(
    db: Session,
    token: str,
    nome: str = "",
    email: str = "",
    senha: str = "",
    telefone: str = "",
    usuario_logado: Usuario | None = None,
) -> Rastreador:
    """Transforma uma conta em rastreador. Cria a conta na hora, se ainda nao existir.

    Conta que ja e rastreadora passa direto: reabrir o link que ja foi usado por quem ja tem o
    papel nao e erro de ninguem, e gastar um uso do convite nesse caso seria queimar o convite a
    toa.
    """
    convite = repo.convite_por_token(db, token)
    if not repo.vale(convite):
        raise NaoEncontrado("Convite de rastreador inválido ou vencido")

    usuario = usuario_logado
    if usuario is None:
        if email and repo_contas.usuario_por_email(db, email):
            # Frase diferente da validacao comum de proposito: aqui o caminho de saida e entrar com
            # a conta que ja existe e reabrir o link, e nao inventar outro email.
            raise ForaDeRegra(
                "Já existe conta com esse email. Entre com ela primeiro e reabra este link."
            )
        problema = servico_contas.validar(db, nome, email, senha, telefone)
        if problema:
            raise ForaDeRegra(problema)
        usuario = servico_contas.criar_usuario(db, nome, email, senha, telefone)

    ja = repo.por_usuario(db, usuario.id)
    if ja is not None:
        return ja

    rastreador = Rastreador(
        usuario_id=usuario.id, criado_por_usuario_id=convite.criado_por_usuario_id
    )
    db.add(rastreador)
    convite.usos += 1
    db.flush()
    return rastreador


def acompanhar(db: Session, rastreador: Rastreador, cla: Cla) -> None:
    """Passa a acompanhar um cla, e conta isso no historico do cla. Repetir nao duplica."""
    if repo.acompanha(db, rastreador, cla.id):
        return
    db.add(RastreadorCla(rastreador_id=rastreador.id, cla_id=cla.id))
    db.flush()
    registrar_da_mentoria(
        db,
        cla.id,
        rastreador,
        "comecou a acompanhar",
        "rastreador",
        rastreador.id,
        f"{rastreador.usuario.nome} (mentoria) passou a acompanhar este clã",
    )


def parar_de_acompanhar(db: Session, rastreador: Rastreador, cla: Cla) -> None:
    ligacao = db.query(RastreadorCla).filter_by(rastreador_id=rastreador.id, cla_id=cla.id).first()
    if ligacao is None:
        return
    db.delete(ligacao)
    db.flush()
    registrar_da_mentoria(
        db,
        cla.id,
        rastreador,
        "parou de acompanhar",
        "rastreador",
        rastreador.id,
        f"{rastreador.usuario.nome} (mentoria) parou de acompanhar este clã",
    )
