"""logo opcional do cla

Uma coluna anulavel em `cla`, guardando o NOME do arquivo dentro de DATA_DIR/logos, e nao o
caminho nem a URL: o endereco publico (/logos/...) e decisao de rota, e mudaria junto com ela.

Nula por definicao, e nao por falta de dado: cla sem logo usa o icone do app, e esse e o estado
correto do cla que ja esta em producao. Por isso nao ha UPDATE nenhum aqui, e por isso a coluna
nunca vira NOT NULL.

ADD COLUMN anulavel e a unica alteracao que o SQLite faz sem recriar a tabela, entao esta revisao
nao mexe em linha nenhuma e nao tem como perder dado. O downgrade precisa do batch porque DROP
COLUMN, esse sim, recria.

Revision ID: c2f83b17ad40
Revises: b7c41a9d2e10
Create Date: 2026-09-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2f83b17ad40"
down_revision: Union[str, None] = "b7c41a9d2e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cla", sa.Column("logo", sa.String(length=120), nullable=True))


def downgrade() -> None:
    # Volta o schema, mas os arquivos em DATA_DIR/logos ficam onde estao: apagar imagem de gente
    # de verdade num downgrade de schema seria perder dado que ninguem pediu para perder.
    with op.batch_alter_table("cla") as lote:
        lote.drop_column("logo")
