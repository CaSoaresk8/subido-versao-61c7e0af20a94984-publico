from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL

USA_SQLITE = DATABASE_URL.startswith("sqlite")

connect_args = {"check_same_thread": False} if USA_SQLITE else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


if USA_SQLITE:

    @event.listens_for(engine, "connect")
    def _ajustar_sqlite(conexao, _registro) -> None:
        """Liga os PRAGMAs em toda conexao nova. Eles nao sao persistentes: valem por conexao."""
        cursor = conexao.cursor()
        # O SQLite ignora FOREIGN KEY por padrao, mesmo com a constraint declarada no schema.
        # Sem isso ele aceita em silencio uma entrega apontando para membro que nao existe, e a
        # partir do multi-cla e a FK que impede um cla enxergar linha do outro.
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL deixa leitura e escrita acontecerem juntas. No modo padrao, uma pessoa salvando
        # trava todo mundo que esta lendo o quadro.
        cursor.execute("PRAGMA journal_mode=WAL")
        # Sem isso, duas escritas ao mesmo tempo dao 'database is locked' na hora. Com isso,
        # a segunda espera ate 5s pela primeira. Arrastar card no kanban e um POST por drop.
        cursor.execute("PRAGMA busy_timeout=5000")
        # Com WAL ligado, NORMAL e seguro contra queda do app; so perde em queda de energia da
        # maquina inteira, e para isso existe o backup.
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
