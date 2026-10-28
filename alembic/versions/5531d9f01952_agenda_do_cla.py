"""agenda do cla: eventos e a conta Google da plataforma que manda os convites

So cria duas tabelas novas. Nao altera nenhuma que ja existe, entao nao encosta em linha nenhuma
de producao: o risco desta revisao e o de um CREATE TABLE, e o downgrade e apagar as duas.

As FKs para membro sao compostas com cla_id, como em todo o resto (ver app/models.py): um evento
do cla A nao consegue apontar quem conduz para um membro do cla B, nem se a aplicacao pedir.

Revision ID: 5531d9f01952
Revises: e1c7b53a90d4
Create Date: 2026-09-19

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5531d9f01952'
down_revision: Union[str, Sequence[str], None] = 'e1c7b53a90d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('evento',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cla_id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=200), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('descricao', sa.Text(), nullable=False),
    sa.Column('inicio', sa.DateTime(), nullable=False),
    sa.Column('duracao_min', sa.Integer(), nullable=False),
    sa.Column('local', sa.String(length=500), nullable=False),
    sa.Column('conduzido_por_id', sa.Integer(), nullable=True),
    sa.Column('criado_por_id', sa.Integer(), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('excluido_em', sa.DateTime(), nullable=True),
    sa.Column('excluido_por_id', sa.Integer(), nullable=True),
    sa.Column('google_evento_id', sa.String(length=200), nullable=False),
    sa.Column('google_status', sa.String(length=20), nullable=False),
    sa.Column('google_erro', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['cla_id', 'conduzido_por_id'], ['membro.cla_id', 'membro.id'], name='fk_evento_conduzido_por', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cla_id', 'criado_por_id'], ['membro.cla_id', 'membro.id'], name='fk_evento_criado_por', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cla_id', 'excluido_por_id'], ['membro.cla_id', 'membro.id'], name='fk_evento_excluido_por', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cla_id'], ['cla.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('evento', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_evento_cla_id'), ['cla_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_evento_inicio'), ['inicio'], unique=False)

    op.create_table('integracao_google',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('token_cifrado', sa.Text(), nullable=False),
    sa.Column('conectado_por_usuario_id', sa.Integer(), nullable=False),
    sa.Column('conectado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['conectado_por_usuario_id'], ['usuario.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('integracao_google')
    with op.batch_alter_table('evento', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_evento_inicio'))
        batch_op.drop_index(batch_op.f('ix_evento_cla_id'))

    op.drop_table('evento')
