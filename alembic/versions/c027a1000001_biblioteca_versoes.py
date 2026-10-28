from alembic import op
import sqlalchemy as sa

revision = "c027a1000001"
down_revision = "501e5397023c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "versao_comunidade",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("autor_id", sa.Integer(), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("autor_publico", sa.String(80), nullable=False),
        sa.Column("nome", sa.String(100), nullable=False),
        sa.Column("numero", sa.String(40), nullable=False),
        sa.Column("resumo", sa.String(240), nullable=False),
        sa.Column("novidades", sa.Text(), nullable=False),
        sa.Column("categoria", sa.String(30), nullable=False),
        sa.Column("repositorio", sa.String(500), nullable=False),
        sa.Column("demonstracao", sa.String(500), nullable=False),
        sa.Column("exemplo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_versao_comunidade_autor_id", "versao_comunidade", ["autor_id"])


def downgrade():
    op.drop_table("versao_comunidade")
