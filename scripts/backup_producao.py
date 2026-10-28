"""Backup do banco de producao, sob demanda.

    python scripts/backup_producao.py

O trabalho de verdade mora em `scripts/deploy.py:backup()`, que e o mesmo que o deploy usa. Duas
implementacoes do backup seria uma delas envelhecendo sem ninguem notar, e a que envelhece e sempre
a que nao roda todo dia. Esta aqui existe porque as vezes se quer o backup sem deploy nenhum: antes
de mexer no banco na mao, ou so para ter uma copia do dia.

O que ela garante, e esta escrito la:
  - copia feita com `sqlite3.backup()` DENTRO da maquina (o banco esta em WAL, e copiar o arquivo
    .db cru traz um banco desatualizado que parece inteiro);
  - arquivo baixado para ~/backups-copyecola, fora do repositorio;
  - o arquivo baixado e aberto e conferido aqui antes de o script dizer que deu certo.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy import backup  # noqa: E402

if __name__ == "__main__":
    print(f"BACKUP OK: {backup()}")
