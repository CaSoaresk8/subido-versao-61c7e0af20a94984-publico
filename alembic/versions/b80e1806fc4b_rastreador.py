"""rastreador: o papel que acompanha pessoas atravessando os clas

Cria tres tabelas novas (rastreador, rastreador_cla, convite_rastreador) e acrescenta duas colunas
anulaveis: `log.rastreador_id` (quem agiu, quando foi a mentoria) e
`tarefa_pessoal.criada_por_rastreador_id` (tarefa combinada com a mentoria, que o rastreador ve; a
pessoal continua so da pessoa).

As duas colunas sao Integer sem FK de proposito: no SQLite, acrescentar chave estrangeira obriga a
RECRIAR a tabela inteira, copiando linha por linha. `log` e `tarefa_pessoal` tem dado de gente
usando o app agora, e um ADD COLUMN nao encosta em nenhuma linha. A integridade fica na aplicacao.

Ensaiada numa copia do banco de producao antes de subir.

Revision ID: b80e1806fc4b
Revises: 5531d9f01952
Create Date: 2026-09-22

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b80e1806fc4b'
down_revision: Union[str, Sequence[str], None] = '5531d9f01952'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('convite_rastreador',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('criado_por_usuario_id', sa.Integer(), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('expira_em', sa.DateTime(), nullable=False),
    sa.Column('max_usos', sa.Integer(), nullable=True),
    sa.Column('usos', sa.Integer(), nullable=False),
    sa.Column('revogado_em', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['criado_por_usuario_id'], ['usuario.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('convite_rastreador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_convite_rastreador_token'), ['token'], unique=True)

    op.create_table('rastreador',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('criado_por_usuario_id', sa.Integer(), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['criado_por_usuario_id'], ['usuario.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('rastreador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rastreador_usuario_id'), ['usuario_id'], unique=True)

    op.create_table('rastreador_cla',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rastreador_id', sa.Integer(), nullable=False),
    sa.Column('cla_id', sa.Integer(), nullable=False),
    sa.Column('desde', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cla_id'], ['cla.id'], ),
    sa.ForeignKeyConstraint(['rastreador_id'], ['rastreador.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('rastreador_id', 'cla_id', name='uq_rastreador_cla')
    )
    with op.batch_alter_table('rastreador_cla', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rastreador_cla_cla_id'), ['cla_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_rastreador_cla_rastreador_id'), ['rastreador_id'], unique=False)

    with op.batch_alter_table('log', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rastreador_id', sa.Integer(), nullable=True))

    with op.batch_alter_table('tarefa_pessoal', schema=None) as batch_op:
        batch_op.add_column(sa.Column('criada_por_rastreador_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_tarefa_pessoal_criada_por_rastreador_id'), ['criada_por_rastreador_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tarefa_pessoal', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tarefa_pessoal_criada_por_rastreador_id'))
        batch_op.drop_column('criada_por_rastreador_id')

    with op.batch_alter_table('log', schema=None) as batch_op:
        batch_op.drop_column('rastreador_id')

    with op.batch_alter_table('rastreador_cla', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rastreador_cla_rastreador_id'))
        batch_op.drop_index(batch_op.f('ix_rastreador_cla_cla_id'))

    op.drop_table('rastreador_cla')
    with op.batch_alter_table('rastreador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rastreador_usuario_id'))

    op.drop_table('rastreador')
    with op.batch_alter_table('convite_rastreador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_convite_rastreador_token'))

    op.drop_table('convite_rastreador')
