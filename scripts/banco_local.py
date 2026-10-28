"""Recria o banco local a partir do backup de producao.

O desenvolvimento do multi-cla acontece inteiro na maquina, contra dados reais, e nao contra um
banco vazio: consulta que parece rapida com zero linha e a que depois trava em producao.

O backup fica em ~/backups-copyecola e NAO entra no repositorio (data/ e *.db estao no .gitignore).

Uso:
    python scripts/banco_local.py                 # usa o backup mais recente
    python scripts/banco_local.py caminho/do.db   # usa um backup especifico
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "copyecola.db"
BACKUPS = Path.home() / "backups-copyecola"
TABELAS = ("membro", "missao", "entrega", "tarefa_pessoal", "coluna", "log")


def escolher_origem() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser()
    if not BACKUPS.is_dir():
        sys.exit(f"FALHOU: {BACKUPS} nao existe. Rode scripts/backup_producao.py antes.")
    candidatos = sorted(BACKUPS.glob("backup-*.db"))
    if not candidatos:
        sys.exit(f"FALHOU: nenhum backup-*.db em {BACKUPS}.")
    return candidatos[-1]


def main() -> None:
    origem = escolher_origem()
    if not origem.is_file():
        sys.exit(f"FALHOU: {origem} nao existe.")

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    # Os arquivos -wal e -shm sao de uma sessao antiga do SQLite. Deixar para tras e como o banco
    # novo acaba com transacao pendente do banco velho.
    for sufixo in ("-wal", "-shm"):
        companheiro = DESTINO.with_name(DESTINO.name + sufixo)
        companheiro.unlink(missing_ok=True)

    shutil.copy2(origem, DESTINO)

    conexao = sqlite3.connect(DESTINO)
    integridade = conexao.execute("pragma integrity_check").fetchone()[0]
    if integridade != "ok":
        sys.exit(f"FALHOU: integrity_check devolveu {integridade!r}")

    total = 0
    for tabela in TABELAS:
        quantas = conexao.execute(f"select count(*) from {tabela}").fetchone()[0]
        total += quantas
        print(f"  {tabela}: {quantas}")
    conexao.close()

    # Zero linha em tudo quer dizer que copiei o arquivo errado, nao que producao esta vazia.
    if total == 0:
        sys.exit("FALHOU: o banco copiado nao tem linha nenhuma em tabela alguma.")

    print(f"origem: {origem}")
    print(f"BANCO LOCAL OK: {DESTINO}")


if __name__ == "__main__":
    main()
