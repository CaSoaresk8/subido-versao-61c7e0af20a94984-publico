from sqlalchemy.orm import Session

from app.escopo import EscopoCla
from app.models import Log


def registrar(
    escopo: EscopoCla,
    acao: str,
    entidade: str,
    entidade_id: int,
    detalhe: str,
    membro_id: int | None = None,
) -> None:
    """Anota o que aconteceu. A tabela so cresce: nada aqui e editado nem apagado depois.

    Nao da commit de proposito. Quem chamou e que decide se a operacao inteira vale, e o registro
    tem que valer junto com ela, nunca separado.

    O membro sai do escopo: era um parametro que cada chamada passava, e passar `membro.id` na mao
    em vinte lugares e um lugar a mais para escrever o id errado. `membro_id` continua ali so para
    o caso de registrar acao de outra pessoa, que hoje nao acontece.
    """
    escopo.db.add(
        Log(
            cla_id=escopo.cla_id,
            membro_id=escopo.membro_id if membro_id is None else membro_id,
            acao=acao,
            entidade=entidade,
            entidade_id=entidade_id,
            detalhe=detalhe,
        )
    )


def registrar_da_mentoria(
    db: Session,
    cla_id: int,
    rastreador,
    acao: str,
    entidade: str,
    entidade_id: int,
    detalhe: str,
) -> None:
    """O mesmo log, para quando quem agiu foi a mentoria e nao um membro do cla.

    `membro_id` fica nulo (o rastreador pode nao participar deste cla) e `rastreador_id` diz quem
    foi. O Caio pediu transparencia com NOME, entao o nome vai no detalhe, que e o texto que a
    pessoa le: ela precisa entender de onde veio a tarefa que apareceu ou o ponto que ela nao
    lancou. Um registro sem nome deixaria a pessoa achando que o app errou.
    """
    db.add(
        Log(
            cla_id=cla_id,
            membro_id=None,
            rastreador_id=rastreador.id,
            acao=acao,
            entidade=entidade,
            entidade_id=entidade_id,
            detalhe=detalhe,
        )
    )
