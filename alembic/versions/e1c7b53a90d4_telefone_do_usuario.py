"""telefone da conta

Uma coluna anulavel em `usuario`, guardando so os digitos com DDD e sem o 55 do pais.

Anulavel, e nao NOT NULL com default: as 17 contas que ja estao em producao nasceram antes deste
campo, e nao existe valor verdadeiro para por nelas. Um default "" deixaria o schema mais rigido e o
dado mais mentiroso, porque "nao informou" e "informou vazio" passariam a ser a mesma linha. O
formulario exige o telefone de quem cria conta daqui em diante; o banco guarda a ausencia de quem
criou antes, que e o que de fato aconteceu.

ADD COLUMN anulavel e a unica alteracao que o SQLite faz sem recriar a tabela, entao esta revisao nao
mexe em linha nenhuma e nao tem como perder dado. O downgrade precisa do batch porque DROP COLUMN,
esse sim, recria.

Revision ID: e1c7b53a90d4
Revises: c2f83b17ad40
Create Date: 2026-09-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1c7b53a90d4"
down_revision: Union[str, None] = "c2f83b17ad40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usuario", sa.Column("telefone", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("usuario") as lote:
        lote.drop_column("telefone")
