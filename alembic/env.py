"""Ambiente do Alembic.

A URL do banco NAO vem do alembic.ini: vem do app.config, que ja le DATABASE_URL do ambiente.
Ter dois lugares dizendo onde o banco esta e como se acaba migrando o banco errado.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app import models  # noqa: F401  (registra as tabelas no Base.metadata)
from app.config import DATABASE_URL
from app.database import Base

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Quando o proprio app chama o Alembic no boot (app/esquema.py), reconfigurar o logging aqui
# apagaria a configuracao do uvicorn e o app subiria mudo.
if config.config_file_name is not None and config.attributes.get("configurar_log", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# render_as_batch e obrigatorio no SQLite: ele nao tem ALTER TABLE de verdade para constraint,
# entao o Alembic recria a tabela, copia o dado e renomeia. Sem isso, adicionar NOT NULL ou
# UNIQUE simplesmente falha.
OPCOES = {
    "target_metadata": target_metadata,
    "render_as_batch": True,
    "compare_type": True,
}


def offline() -> None:
    context.configure(
        url=DATABASE_URL,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **OPCOES,
    )
    with context.begin_transaction():
        context.run_migrations()


def _ddl_dentro_da_transacao(engine) -> None:
    """Faz o CREATE/DROP TABLE da revisao entrar na transacao em vez de ficar gravado na hora.

    O driver do SQLite (pysqlite) abre transacao sozinho antes de INSERT/UPDATE/DELETE, mas nao
    antes de DDL: CREATE TABLE sai em autocommit e fica gravado mesmo que a revisao estoure na
    linha seguinte. Isso foi medido, nao suposto: uma revisao que falhou no meio deixou as tabelas
    `usuario` e `cla` criadas no banco com a versao do Alembic ainda na anterior, e a tentativa
    seguinte morreria em "table usuario already exists" em vez de recomecar do zero.

    Desligar o controle do driver e emitir o BEGIN na mao poe o DDL dentro da transacao. Com isso,
    revisao que falha no meio nao aconteceu, que e a unica forma de "migracao falhou" que da para
    tratar sem restaurar backup.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _sem_begin_implicito(dbapi_conexao, _registro) -> None:
        dbapi_conexao.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_explicito(conexao) -> None:
        conexao.exec_driver_sql("BEGIN")


def online() -> None:
    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    _ddl_dentro_da_transacao(engine)
    with engine.connect() as conexao:
        context.configure(connection=conexao, **OPCOES)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    offline()
else:
    online()
