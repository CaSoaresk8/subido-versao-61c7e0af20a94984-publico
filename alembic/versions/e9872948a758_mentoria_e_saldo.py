"""mentoria e saldo: as consultorias do rastreador com cada pessoa

So cria duas tabelas novas (acompanhamento e mentoria) e nao encosta em nenhuma que ja existe.
As FKs para membro sao compostas com cla_id, como em todo o resto.

Revision ID: e9872948a758
Revises: b80e1806fc4b
Create Date: 2026-09-23

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9872948a758'
down_revision: Union[str, Sequence[str], None] = 'b80e1806fc4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('acompanhamento',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cla_id', sa.Integer(), nullable=False),
    sa.Column('membro_id', sa.Integer(), nullable=False),
    sa.Column('mensais_total', sa.Integer(), nullable=False),
    sa.Column('livres_total', sa.Integer(), nullable=False),
    sa.Column('anotacao', sa.Text(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cla_id', 'membro_id'], ['membro.cla_id', 'membro.id'], name='fk_acompanhamento_membro', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cla_id'], ['cla.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cla_id', 'membro_id', name='uq_acompanhamento_membro')
    )
    with op.batch_alter_table('acompanhamento', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_acompanhamento_cla_id'), ['cla_id'], unique=False)

    op.create_table('mentoria',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cla_id', sa.Integer(), nullable=False),
    sa.Column('membro_id', sa.Integer(), nullable=False),
    sa.Column('rastreador_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('inicio', sa.DateTime(), nullable=False),
    sa.Column('duracao_min', sa.Integer(), nullable=False),
    sa.Column('local', sa.String(length=500), nullable=False),
    sa.Column('situacao', sa.String(length=20), nullable=False),
    sa.Column('anotacao', sa.Text(), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cla_id', 'membro_id'], ['membro.cla_id', 'membro.id'], name='fk_mentoria_membro', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cla_id'], ['cla.id'], ),
    sa.ForeignKeyConstraint(['rastreador_id'], ['rastreador.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('mentoria', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mentoria_cla_id'), ['cla_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mentoria_membro_id'), ['membro_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mentoria_rastreador_id'), ['rastreador_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('mentoria', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mentoria_rastreador_id'))
        batch_op.drop_index(batch_op.f('ix_mentoria_membro_id'))
        batch_op.drop_index(batch_op.f('ix_mentoria_cla_id'))

    op.drop_table('mentoria')
    with op.batch_alter_table('acompanhamento', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_acompanhamento_cla_id'))

    op.drop_table('acompanhamento')
