"""multi cla: usuario separado de membro, e cla_id em tudo

O que esta revisao faz, na ordem em que faz:

1. Confere que todo `membro.email` existe e e unico ignorando caixa. Se nao for, ABORTA antes de
   tocar em DDL: o email e a chave que liga cada membro ao usuario novo, e falhar antes de mexer
   no schema e melhor que descobrir com o banco pela metade.
2. Cria `usuario` e `cla`.
3. Insere o cla 1, com o nome que hoje esta na variavel de ambiente CLA_NOME, SE existir membro
   para migrar. Banco vazio nao ganha cla: ver o comentario no proprio INSERT.
4. Cria um `usuario` por `membro` existente, com o MESMO email e o MESMO senha_hash. Ninguem
   precisa redefinir senha: o hash nao e recalculado, e copiado.
5. Recria as seis tabelas com `cla_id`, todas apontando para o cla 1.

`membro.id` e PRESERVADO. E isso que mantem em pe as sessoes que ja estao em campo: o cookie das
17 pessoas guarda `membro_id`, e app/deps.py converte esse cookie lendo o membro por id. Recriar
membro com ids novos derrubaria todo mundo no login, num deploy que nao era sobre login.

Por que recriar a tabela na mao em vez de usar batch_alter_table: as FKs antigas nao tem nome
(`FOREIGN KEY(membro_id) REFERENCES membro(id)` sem CONSTRAINT), e no SQLite nao da para remover
constraint sem nome pelo batch sem descrever a tabela inteira de qualquer jeito. Escrevendo o
CREATE TABLE final de forma explicita, o que o banco vai ficar esta legivel aqui, linha por linha.

Cada troca confere a contagem de linhas antes e depois, e no fim roda PRAGMA foreign_key_check.
Migracao que perde linha ou deixa FK orfa para aqui, nao em producao.

Revision ID: b7c41a9d2e10
Revises: 4351f26e4926
Create Date: 2026-09-17

"""

import os
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c41a9d2e10"
down_revision: Union[str, Sequence[str], None] = "4351f26e4926"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CLA = 1


def _agora() -> str:
    """O instante no MESMO formato que o app grava, como texto.

    Nao da para passar `sa.func.current_timestamp()` como valor de bindparam: bindparam e dado, e o
    driver do SQLite nao sabe converter uma funcao SQL em dado ("type 'current_timestamp' is not
    supported").

    O formato tem microssegundos porque e assim que o app escreve: conferi em membro.criado_em de
    verdade, que esta em "2026-09-16 21:15:13.512715". O CURRENT_TIMESTAMP do SQLite sai sem eles.
    O SQLAlchemy le as duas formas, entao isso nao quebraria nada hoje; e o tipo de diferenca que
    fica guardada no banco por anos e aparece no dia em que alguem comparar como texto.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def _exigir_fk_desligada() -> None:
    """Recriar tabela no SQLite exige PRAGMA foreign_keys=OFF. Conferir em vez de supor.

    O alembic/env.py monta o proprio engine, e o listener que liga os PRAGMAs vive no engine do
    app, entao aqui a FK ja chega desligada. Isso e um detalhe de como o env.py foi escrito, e
    detalhe muda: se um dia mudar, o DROP TABLE abaixo falharia com "FOREIGN KEY constraint
    failed" no meio da migracao, e a mensagem nao diria o motivo. Esta diz.
    """
    ligada = op.get_bind().exec_driver_sql("PRAGMA foreign_keys").scalar()
    if ligada:
        raise RuntimeError(
            "Esta revisao recria tabelas e precisa de PRAGMA foreign_keys=OFF na conexao do "
            "Alembic. Ela esta ON. Rode a migracao por uma conexao sem o PRAGMA (o "
            "alembic/env.py monta o proprio engine justamente para isso)."
        )


def _exigir_email_utilizavel() -> None:
    """Sem email unico e presente nao da para ligar membro a usuario. Aborta antes de qualquer DDL.

    A comparacao ignora caixa e espaco porque o login novo procura por email em minusculas: dois
    membros com "A@x.com" e "a@x.com" sao distintos hoje e virariam a mesma conta depois, e
    "virariam a mesma conta" quer dizer que um dos dois passa a entrar na conta do outro.
    """
    bind = op.get_bind()
    vazios = bind.exec_driver_sql(
        "SELECT COUNT(*) FROM membro WHERE email IS NULL OR TRIM(email) = ''"
    ).scalar()
    if vazios:
        raise RuntimeError(f"{vazios} membro(s) sem email. Preencha antes de migrar.")

    repetidos = bind.exec_driver_sql(
        "SELECT LOWER(TRIM(email)), COUNT(*) FROM membro "
        "GROUP BY LOWER(TRIM(email)) HAVING COUNT(*) > 1"
    ).all()
    if repetidos:
        lista = ", ".join(f"{email} ({vezes}x)" for email, vezes in repetidos)
        raise RuntimeError(f"Email repetido em membro: {lista}. Resolva antes de migrar.")


def _substituir(nome: str, colunas: Sequence[str], select_sql: str) -> None:
    """Copia a tabela antiga para a nova (`novo_<nome>`), troca uma pela outra e confere a conta."""
    bind = op.get_bind()
    antes = bind.exec_driver_sql(f"SELECT COUNT(*) FROM {nome}").scalar()
    op.execute(f"INSERT INTO novo_{nome} ({', '.join(colunas)}) {select_sql}")
    depois = bind.exec_driver_sql(f"SELECT COUNT(*) FROM novo_{nome}").scalar()
    if antes != depois:
        raise RuntimeError(
            f"{nome}: {antes} linhas antes, {depois} depois da copia. Nao troco a tabela com "
            "linha faltando; restaure o backup e investigue."
        )
    op.drop_table(nome)
    op.rename_table(f"novo_{nome}", nome)


def _fk_membro(coluna: str, nome: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["cla_id", coluna], ["membro.cla_id", "membro.id"], name=nome, ondelete="RESTRICT"
    )


def upgrade() -> None:
    _exigir_fk_desligada()
    _exigir_email_utilizavel()

    op.create_table(
        "usuario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("senha_hash", sa.String(length=255), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usuario_email", "usuario", ["email"], unique=True)

    op.create_table(
        "cla",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("criado_por_id", sa.Integer(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["criado_por_id"], ["usuario.id"], name="fk_cla_criado_por"),
        sa.PrimaryKeyConstraint("id"),
    )

    # O cla 1 e o cla que ja existia, entao ele so nasce se existir gente para migrar. Num banco
    # vazio (dev, teste, instalacao nova) nao ha cla nenhum a preservar, e criar um aqui deixaria
    # para tras um cla sem membros em que ninguem consegue entrar: as portas do app sao criar um
    # cla ou usar um convite, e nenhuma das duas cai num cla orfao. Todos os SELECT daqui para
    # baixo saem de `membro`, entao com zero membros nada mais referencia este id.
    #
    # criado_por_id fica NULL: este cla nao foi criado por ninguem dentro do app, ele ja existia
    # como variavel de ambiente. Inventar um criador aqui seria escrever no banco algo que nunca
    # aconteceu.
    tem_membro = op.get_bind().exec_driver_sql("SELECT COUNT(*) FROM membro").scalar()
    if tem_membro:
        op.execute(
            sa.text(
                "INSERT INTO cla (id, nome, criado_por_id, criado_em) "
                "VALUES (:id, :nome, NULL, :agora)"
            ).bindparams(
                # CLA_NOME saiu do config nesta mesma serie de mudancas, mas continua lido AQUI: em
                # producao a variavel ainda esta definida na maquina, e e dela que sai o nome certo
                # do cla que esta sendo migrado. O default cobre quem nunca a definiu.
                id=CLA,
                nome=os.getenv("CLA_NOME", "Copy e Cola"),
                agora=_agora(),
            )
        )

    # Uma conta por membro. O senha_hash e copiado, nao recalculado: as senhas continuam valendo.
    op.execute(
        "INSERT INTO usuario (nome, email, senha_hash, criado_em) "
        "SELECT nome, LOWER(TRIM(email)), senha_hash, criado_em FROM membro ORDER BY id"
    )

    op.create_table(
        "novo_membro",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cla_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("entrou_em", sa.DateTime(), nullable=False),
        sa.Column("ordem_quadro", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["cla_id"], ["cla.id"], name="fk_membro_cla"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], name="fk_membro_usuario"),
        sa.PrimaryKeyConstraint("id"),
        # (cla_id, usuario_id): a mesma conta nao entra duas vezes no mesmo cla.
        sa.UniqueConstraint("cla_id", "usuario_id", name="uq_membro_cla_usuario"),
        # (cla_id, id): alvo das FKs compostas das outras tabelas. Parece redundante porque id ja
        # e unico, mas sem ele o SQLite recusa declarar FK composta apontando para ca.
        sa.UniqueConstraint("cla_id", "id", name="uq_membro_cla_id"),
    )
    # JOIN por email, que o passo acima acabou de garantir unico e presente. O id do membro vem
    # do SELECT e nao do autoincrement: e ele que os cookies em campo apontam.
    _substituir(
        "membro",
        ["id", "cla_id", "usuario_id", "nome", "entrou_em", "ordem_quadro"],
        f"SELECT m.id, {CLA}, u.id, m.nome, m.criado_em, m.ordem_quadro "
        "FROM membro m JOIN usuario u ON u.email = LOWER(TRIM(m.email))",
    )
    op.create_index("ix_membro_cla_id", "membro", ["cla_id"])
    op.create_index("ix_membro_usuario_id", "membro", ["usuario_id"])

    op.create_table(
        "convite",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cla_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("criado_por_id", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("expira_em", sa.DateTime(), nullable=False),
        sa.Column("max_usos", sa.Integer(), nullable=True),
        sa.Column("usos", sa.Integer(), nullable=False),
        sa.Column("revogado_em", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["cla_id"], ["cla.id"], name="fk_convite_cla"),
        _fk_membro("criado_por_id", "fk_convite_criado_por"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_convite_cla_id", "convite", ["cla_id"])
    op.create_index("ix_convite_token", "convite", ["token"], unique=True)

    op.create_table(
        "novo_missao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cla_id", sa.Integer(), nullable=False),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("pontos", sa.Integer(), nullable=False),
        sa.Column("vencimento", sa.Date(), nullable=True),
        sa.Column("criada_por_id", sa.Integer(), nullable=False),
        sa.Column("criada_em", sa.DateTime(), nullable=False),
        sa.Column("exige_resposta", sa.Boolean(), nullable=False),
        sa.Column("rotulo_resposta", sa.String(length=200), nullable=False),
        sa.Column("excluida_em", sa.DateTime(), nullable=True),
        sa.Column("excluida_por_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["cla_id"], ["cla.id"], name="fk_missao_cla"),
        _fk_membro("criada_por_id", "fk_missao_criada_por"),
        _fk_membro("excluida_por_id", "fk_missao_excluida_por"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cla_id", "id", name="uq_missao_cla_id"),
    )
    _substituir(
        "missao",
        [
            "id",
            "cla_id",
            "titulo",
            "descricao",
            "pontos",
            "vencimento",
            "criada_por_id",
            "criada_em",
            "exige_resposta",
            "rotulo_resposta",
            "excluida_em",
            "excluida_por_id",
        ],
        f"SELECT id, {CLA}, titulo, descricao, pontos, vencimento, criada_por_id, criada_em, "
        "exige_resposta, rotulo_resposta, excluida_em, excluida_por_id FROM missao",
    )
    op.create_index("ix_missao_cla_id", "missao", ["cla_id"])

    op.create_table(
        "novo_coluna",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cla_id", sa.Integer(), nullable=False),
        sa.Column("membro_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=60), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("criada_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cla_id"], ["cla.id"], name="fk_coluna_cla"),
        _fk_membro("membro_id", "fk_coluna_membro"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cla_id", "id", name="uq_coluna_cla_id"),
    )
    _substituir(
        "coluna",
        ["id", "cla_id", "membro_id", "nome", "ordem", "criada_em"],
        f"SELECT id, {CLA}, membro_id, nome, ordem, criada_em FROM coluna",
    )
    op.create_index("ix_coluna_cla_id", "coluna", ["cla_id"])
    op.create_index("ix_coluna_membro_id", "coluna", ["membro_id"])

    op.create_table(
        "novo_entrega",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cla_id", sa.Integer(), nullable=False),
        sa.Column("missao_id", sa.Integer(), nullable=False),
        sa.Column("membro_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resposta", sa.Text(), nullable=False),
        sa.Column("observacao", sa.Text(), nullable=False),
        sa.Column("concluida_em", sa.DateTime(), nullable=True),
        sa.Column("atualizada_em", sa.DateTime(), nullable=False),
        sa.Column("coluna_id", sa.Integer(), nullable=True),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["cla_id"], ["cla.id"], name="fk_entrega_cla"),
        sa.ForeignKeyConstraint(
            ["cla_id", "missao_id"], ["missao.cla_id", "missao.id"], name="fk_entrega_missao"
        ),
        sa.ForeignKeyConstraint(
            ["cla_id", "coluna_id"], ["coluna.cla_id", "coluna.id"], name="fk_entrega_coluna"
        ),
        _fk_membro("membro_id", "fk_entrega_membro"),
        sa.PrimaryKeyConstraint("id"),
        # Substitui a UNIQUE(missao_id, membro_id) antiga: com varios clas, a mesma dupla de ids
        # pode existir em clas diferentes e as duas linhas sao legitimas.
        sa.UniqueConstraint(
            "cla_id", "missao_id", "membro_id", name="uq_entrega_cla_missao_membro"
        ),
    )
    _substituir(
        "entrega",
        [
            "id",
            "cla_id",
            "missao_id",
            "membro_id",
            "status",
            "resposta",
            "observacao",
            "concluida_em",
            "atualizada_em",
            "coluna_id",
            "ordem",
        ],
        f"SELECT id, {CLA}, missao_id, membro_id, status, resposta, observacao, concluida_em, "
        "atualizada_em, coluna_id, ordem FROM entrega",
    )
    op.create_index("ix_entrega_cla_id", "entrega", ["cla_id"])

    op.create_table(
        "novo_tarefa_pessoal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cla_id", sa.Integer(), nullable=False),
        sa.Column("membro_id", sa.Integer(), nullable=False),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("prazo", sa.Date(), nullable=True),
        sa.Column("criada_em", sa.DateTime(), nullable=False),
        sa.Column("excluida_em", sa.DateTime(), nullable=True),
        sa.Column("coluna_id", sa.Integer(), nullable=True),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["cla_id"], ["cla.id"], name="fk_tarefa_cla"),
        sa.ForeignKeyConstraint(
            ["cla_id", "coluna_id"], ["coluna.cla_id", "coluna.id"], name="fk_tarefa_coluna"
        ),
        _fk_membro("membro_id", "fk_tarefa_membro"),
        sa.PrimaryKeyConstraint("id"),
    )
    _substituir(
        "tarefa_pessoal",
        [
            "id",
            "cla_id",
            "membro_id",
            "titulo",
            "descricao",
            "status",
            "prazo",
            "criada_em",
            "excluida_em",
            "coluna_id",
            "ordem",
        ],
        f"SELECT id, {CLA}, membro_id, titulo, descricao, status, prazo, criada_em, excluida_em, "
        "coluna_id, ordem FROM tarefa_pessoal",
    )
    op.create_index("ix_tarefa_pessoal_cla_id", "tarefa_pessoal", ["cla_id"])

    op.create_table(
        "novo_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cla_id", sa.Integer(), nullable=False),
        sa.Column("membro_id", sa.Integer(), nullable=True),
        sa.Column("acao", sa.String(length=40), nullable=False),
        sa.Column("entidade", sa.String(length=40), nullable=False),
        sa.Column("entidade_id", sa.Integer(), nullable=False),
        sa.Column("detalhe", sa.Text(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cla_id"], ["cla.id"], name="fk_log_cla"),
        _fk_membro("membro_id", "fk_log_membro"),
        sa.PrimaryKeyConstraint("id"),
    )
    _substituir(
        "log",
        ["id", "cla_id", "membro_id", "acao", "entidade", "entidade_id", "detalhe", "criado_em"],
        f"SELECT id, {CLA}, membro_id, acao, entidade, entidade_id, detalhe, criado_em FROM log",
    )
    op.create_index("ix_log_cla_id", "log", ["cla_id"])

    _conferir_integridade()


def _conferir_integridade() -> None:
    """PRAGMA foreign_key_check: a prova de que nenhuma linha ficou apontando para o vazio.

    As FKs estavam desligadas durante a migracao, entao o banco aceitou tudo em silencio. Esta e a
    conferencia que faltava: ela varre as tabelas e devolve uma linha por violacao. Se voltar
    alguma, a transacao inteira volta atras e producao continua como estava.
    """
    violacoes = op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").all()
    if violacoes:
        raise RuntimeError(
            f"{len(violacoes)} violacao(es) de FK depois da migracao: {violacoes[:5]}. "
            "Nada foi gravado."
        )


def downgrade() -> None:
    """Nao tem volta escrita, e isso e deliberado.

    Um downgrade aqui teria que jogar fora as contas, decidir qual cla sobrevive e reconstruir seis
    tabelas. Seria codigo que nunca roda em teste e roda uma vez, no pior momento possivel. O
    caminho de volta e o backup tirado antes da migracao, que e testado por definicao: e uma copia
    do banco que estava funcionando.
    """
    raise NotImplementedError(
        "Sem downgrade. Para voltar, restaure o backup feito antes de rodar esta revisao."
    )
