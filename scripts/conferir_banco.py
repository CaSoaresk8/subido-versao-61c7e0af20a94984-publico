"""Mostra o estado do banco local: revisao do Alembic, contagem por tabela e FK orfa.

Serve de conferencia depois de cada migracao. O numero que importa e o de antes: migracao que
muda a contagem de membro, missao, entrega ou tarefa perdeu dado, mesmo sem ter dado erro.

Uso:
    python scripts/conferir_banco.py [caminho/do.db]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TABELAS = ("membro", "missao", "entrega", "tarefa_pessoal", "coluna", "log")


def main() -> None:
    caminho = (
        Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else RAIZ / "data" / "copyecola.db"
    )
    if not caminho.is_file():
        sys.exit(f"FALHOU: {caminho} nao existe.")

    conexao = sqlite3.connect(caminho)
    existentes = {
        r[0] for r in conexao.execute("select name from sqlite_master where type='table'")
    }

    print(f"banco: {caminho}")
    if "alembic_version" in existentes:
        versoes = [r[0] for r in conexao.execute("select version_num from alembic_version")]
        print(f"alembic: {', '.join(versoes) or 'tabela vazia'}")
    else:
        print("alembic: sem tabela alembic_version (banco ainda nao migrado)")

    for tabela in TABELAS:
        if tabela in existentes:
            print(f"  {tabela}: {conexao.execute(f'select count(*) from {tabela}').fetchone()[0]}")
        else:
            print(f"  {tabela}: NAO EXISTE")

    integridade = conexao.execute("pragma integrity_check").fetchone()[0]
    orfas = conexao.execute("pragma foreign_key_check").fetchall()
    conexao.close()

    print(f"integridade: {integridade}")
    print(f"fk orfas: {orfas or 'nenhuma'}")
    if integridade != "ok" or orfas:
        sys.exit("FALHOU: banco inconsistente.")


if __name__ == "__main__":
    main()
