"""Montagem de cla, conta e escopo para os testes que falam direto com servico e repositorio.

Existe por dois motivos.

O primeiro: depois do multi-cla, criar uma pessoa deixou de ser uma linha. Sao tres (cla, usuario,
membro) e cada tabela de dado carrega cla_id. Repetir isso em quatro modulos de teste e convidar
cada um a montar um cenario um pouco diferente, e a diferenca aparece como teste que passa sem
provar nada.

O segundo, mais importante: `banco()` liga PRAGMA foreign_keys=ON, igual ao engine do app. Os
modulos de teste montavam o engine na mao com create_engine, e engine sem esse PRAGMA aceita FK
quebrada em silencio. As FKs compostas (cla_id, membro_id) sao metade da garantia de isolamento
entre clas, entao um teste rodando com elas desligadas provaria menos do que parece: cruzaria cla
sem reclamar e passaria verde.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.escopo import EscopoCla
from app.models import Cla, Membro, Usuario


@contextmanager
def banco(prefixo: str) -> Iterator[tuple[sessionmaker[Session], Engine]]:
    """Banco em arquivo proprio, com os PRAGMAs do app, apagado na saida.

    Arquivo e nao :memory: porque o schema tem FK composta e a intencao e exercitar o mesmo SQLite
    que roda em producao, inclusive o `foreign_keys=ON` que recusa linha cruzando cla.

    Context manager e nao fixture porque cada modulo de teste tem escopo e cenario proprios, e o
    `try/finally` aqui garante que a pasta temporaria vai embora mesmo quando o cenario estoura no
    meio da montagem.
    """
    pasta = Path(tempfile.mkdtemp(prefix=f"copyecola-{prefixo}-"))
    engine = create_engine(f"sqlite:///{pasta / 'teste.db'}")

    @event.listens_for(engine, "connect")
    def _ligar_fk(conexao, _registro) -> None:
        cursor = conexao.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        engine.dispose()
        shutil.rmtree(pasta, ignore_errors=True)


def criar_cla(db: Session, nome: str) -> Cla:
    cla = Cla(nome=nome)
    db.add(cla)
    db.flush()
    return cla


def entrar(db: Session, cla: Cla, nome: str, email: str | None = None) -> Membro:
    """Uma conta nova participando do cla. O email e derivado do nome quando nao importa qual e.

    O senha_hash e um literal: nenhum teste que usa esta fabrica faz login, e gerar hash scrypt de
    verdade custa caro o suficiente para aparecer no tempo da suite. Quem testa login passa pelo
    HTTP /criar-conta, onde o hash e o de verdade.
    """
    apelido = nome.split()[0].lower()
    usuario = Usuario(nome=nome, email=email or f"{apelido}@teste.local", senha_hash="x")
    db.add(usuario)
    db.flush()
    membro = Membro(cla_id=cla.id, usuario_id=usuario.id, nome=nome)
    db.add(membro)
    db.flush()
    return membro


def escopo(db: Session, membro: Membro) -> EscopoCla:
    return EscopoCla(db=db, membro=membro)


def qualquer_membro(db: Session) -> Membro:
    """O membro de menor id do banco, para o teste montar um escopo sem passar pelo login.

    E o unico select sem cla que os testes fazem, e ele mora aqui de proposito: e montagem de
    cenario, nao codigo de app. Em producao quem resolve isso e app/deps.py, lendo a sessao do
    cookie, e nenhum repositorio tem funcao equivalente justamente por isso.
    """
    membro = db.scalars(select(Membro).order_by(Membro.id)).first()
    if membro is None:
        raise AssertionError("banco de teste sem membro: o cenario nao foi montado")
    return membro
