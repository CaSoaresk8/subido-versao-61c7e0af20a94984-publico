"""As consultas que rodam ANTES de existir um cla ativo, e por isso nao recebem escopo.

Todo o resto de repositorios/ e escopado por construcao: recebe EscopoCla e nunca ve linha de
outro cla. Aqui fica a excecao, reunida num arquivo so para ela ser visivel em vez de ficar
espalhada: login (quem e essa conta), escolha do cla ativo (de quais clas essa conta participa) e
o convite (que vale justamente para quem ainda nao esta dentro).

As tres perguntas sao sobre a CONTA, nao sobre um cla, entao um filtro por cla_id aqui nao teria
o que filtrar. O isolamento neste nivel e o usuario_id e o token, e cada funcao abaixo diz qual
dos dois esta usando.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Cla, Convite, Membro, Usuario


def usuario_por_email(db: Session, email: str) -> Usuario | None:
    """O login. Email e unico no banco inteiro, entao esta busca nao tem cla nenhum a considerar."""
    return db.scalar(select(Usuario).where(func.lower(Usuario.email) == email.strip().lower()))


def usuario_por_id(db: Session, usuario_id: int) -> Usuario | None:
    return db.get(Usuario, usuario_id)


def membro_por_id(db: Session, membro_id: int) -> Membro | None:
    """Busca sem cla, e existe por um motivo so: cookie de antes do multi-cla.

    O cookie em campo guarda `membro_id` e nada mais, entao para converte-lo e preciso ler o
    membro sem saber o cla. Nao chame daqui de nenhum outro lugar: dentro do app, membro por id e
    `repositorios/membros.py:por_id`, que passa pelo escopo. Quando nao existir mais cookie antigo
    em campo, esta funcao sai junto com a conversao em deps.py.
    """
    stmt = select(Membro).where(Membro.id == membro_id).options(joinedload(Membro.cla))
    return db.scalar(stmt)


def membros_do_usuario(db: Session, usuario_id: int) -> list[Membro]:
    """De quais clas a conta participa, na ordem em que entrou. Alimenta o seletor de cla ativo.

    Carrega o cla junto porque quem chama vai mostrar o nome de cada um; sem isso seria uma
    consulta por cla so para escrever o nome na tela.
    """
    stmt = (
        select(Membro)
        .where(Membro.usuario_id == usuario_id)
        .options(joinedload(Membro.cla))
        .order_by(Membro.entrou_em, Membro.id)
    )
    return list(db.scalars(stmt))


def membro_do_usuario_no_cla(db: Session, usuario_id: int, cla_id: int) -> Membro | None:
    """A participacao especifica, para confirmar que o cla_ativo_id do cookie ainda vale.

    E aqui que um cookie com cla_id que a pessoa nao participa (ou nao participa mais) morre:
    devolve None, e quem chama trata como sessao sem cla.
    """
    stmt = (
        select(Membro)
        .where(Membro.usuario_id == usuario_id, Membro.cla_id == cla_id)
        .options(joinedload(Membro.cla))
    )
    return db.scalar(stmt)


def cla_por_id(db: Session, cla_id: int) -> Cla | None:
    return db.get(Cla, cla_id)


def convite_por_token(db: Session, token: str) -> Convite | None:
    """O convite e procurado por quem ainda nao esta no cla: o token E a credencial da busca.

    Sem filtro por cla de proposito, porque e o token que diz de qual cla se trata. Se ele valia,
    quem decide e servicos/convites.py, que olha validade, revogacao e limite de usos.
    """
    return db.scalar(select(Convite).where(Convite.token == token.strip()))
