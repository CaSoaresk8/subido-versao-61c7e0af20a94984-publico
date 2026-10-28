"""acompanhamento semanal: perfil de cada pessoa, responsavel da semana e o diario

So cria tres tabelas novas (perfil_membro, responsavel_semana, diario_entrada) e nao encosta em
nenhuma que ja existe. FKs para membro compostas com cla_id, como em todo o resto.

Revision ID: 501e5397023c
Revises: e9872948a758
Create Date: 2026-10-20

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '501e5397023c'
down_revision: Union[str, Sequence[str], None] = 'e9872948a758'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('diario_entrada',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cla_id', sa.Integer(), nullable=False),
    sa.Column('membro_id', sa.Integer(), nullable=False),
    sa.Column('semana', sa.Date(), nullable=False),
    sa.Column('autor_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('como_esta', sa.Text(), nullable=False),
    sa.Column('combinados', sa.Text(), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cla_id', 'autor_id'], ['membro.cla_id', 'membro.id'], name='fk_diario_autor', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cla_id', 'membro_id'], ['membro.cla_id', 'membro.id'], name='fk_diario_membro', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cla_id'], ['cla.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cla_id', 'membro_id', 'semana', name='uq_diario_semana')
    )
    with op.batch_alter_table('diario_entrada', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_diario_entrada_cla_id'), ['cla_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_diario_entrada_membro_id'), ['membro_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_diario_entrada_semana'), ['semana'], unique=False)

    op.create_table('perfil_membro',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cla_id', sa.Integer(), nullable=False),
    sa.Column('membro_id', sa.Integer(), nullable=False),
    sa.Column('sobre', sa.Text(), nullable=False),
    sa.Column('metas', sa.Text(), nullable=False),
    sa.Column('dificuldades', sa.Text(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_por_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['cla_id', 'atualizado_por_id'], ['membro.cla_id', 'membro.id'], name='fk_perfil_atualizado_por', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cla_id', 'membro_id'], ['membro.cla_id', 'membro.id'], name='fk_perfil_membro', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cla_id'], ['cla.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cla_id', 'membro_id', name='uq_perfil_membro')
    )
    with op.batch_alter_table('perfil_membro', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_perfil_membro_cla_id'), ['cla_id'], unique=False)

    op.create_table('responsavel_semana',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cla_id', sa.Integer(), nullable=False),
    sa.Column('semana', sa.Date(), nullable=False),
    sa.Column('membro_id', sa.Integer(), nullable=False),
    sa.Column('desde', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cla_id', 'membro_id'], ['membro.cla_id', 'membro.id'], name='fk_responsavel_membro', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cla_id'], ['cla.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cla_id', 'semana', name='uq_responsavel_semana')
    )
    with op.batch_alter_table('responsavel_semana', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_responsavel_semana_cla_id'), ['cla_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('responsavel_semana', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_responsavel_semana_cla_id'))

    op.drop_table('responsavel_semana')
    with op.batch_alter_table('perfil_membro', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_perfil_membro_cla_id'))

    op.drop_table('perfil_membro')
    with op.batch_alter_table('diario_entrada', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_diario_entrada_semana'))
        batch_op.drop_index(batch_op.f('ix_diario_entrada_membro_id'))
        batch_op.drop_index(batch_op.f('ix_diario_entrada_cla_id'))

    op.drop_table('diario_entrada')
