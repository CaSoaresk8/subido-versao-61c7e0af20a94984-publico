from alembic import op
import sqlalchemy as sa

revision = "c027a1000002"
down_revision = "c027a1000001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "projeto_versao",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("autor_id", sa.Integer(), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("nome", sa.String(100), nullable=False),
        sa.Column("estado", sa.String(30), nullable=False),
        sa.Column("base_id", sa.Integer(), sa.ForeignKey("versao_comunidade.id")),
        sa.Column("configuracao", sa.Text(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_projeto_versao_autor_id", "projeto_versao", ["autor_id"])
    op.create_table(
        "conexao_central",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("autor_id", sa.Integer(), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("provedor", sa.String(20), nullable=False),
        sa.Column("token_cifrado", sa.Text(), nullable=False),
        sa.Column("identidade", sa.String(150), nullable=False),
        sa.UniqueConstraint("autor_id", "provedor", name="uq_conexao_central"),
    )
    op.create_index("ix_conexao_central_autor_id", "conexao_central", ["autor_id"])
    op.create_table(
        "tarefa_central",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("projeto_id", sa.String(32), sa.ForeignKey("projeto_versao.id"), nullable=False),
        sa.Column("autor_id", sa.Integer(), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("acao", sa.String(30), nullable=False),
        sa.Column("estado", sa.String(30), nullable=False),
        sa.Column("dados", sa.Text(), nullable=False),
        sa.Column("mensagem", sa.Text(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
    )
    for campo in ("projeto_id", "autor_id", "estado"):
        op.create_index("ix_tarefa_central_" + campo, "tarefa_central", [campo])


def downgrade():
    op.drop_table("tarefa_central")
    op.drop_table("conexao_central")
    op.drop_table("projeto_versao")
