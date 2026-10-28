"""Unico dono do schema do banco, e o backup que protege cada migracao.

Antes daqui existiam dois donos: Base.metadata.create_all criava as tabelas e app/migracao.py ia
adicionando coluna por coluna com ALTER TABLE. Dois donos e como o banco fica diferente do que
o codigo espera sem ninguem perceber, porque cada um so sabe da metade que faz.

Agora e so o Alembic. As revisoes ficam em alembic/versions/ e valem tanto para o banco de
producao quanto para o banco temporario do teste.

**O app migra sozinho ao subir**, e e por isso que o backup mora aqui. Deploy e migracao sao o
mesmo instante: quando a imagem nova comeca, `atualizar()` roda antes de a primeira pessoa ser
atendida. Um `ALTER TABLE` que apague a coluna errada, ou um `batch_alter_table` do SQLite (que
recria a tabela inteira) interrompido no meio, acontece ali, sem ninguem olhando, com gente usando
o app. Por isso a regra: **enquanto houver revisao pendente, nada roda antes de existir uma copia
completa do banco de antes**. Se o backup falhar, a migracao NAO acontece e o app nao sobe; subir
sem rede seria trocar um problema visivel por um invisivel.

A copia usa `sqlite3.backup()`, e nao `cp`: o banco esta em modo WAL, e copiar so o arquivo .db
deixa de fora tudo o que ainda esta no -wal. Um backup assim abre, passa no integrity_check e
mesmo assim esta velho, que e a pior forma de backup ruim.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.config import DATABASE_URL
from app.database import engine

RAIZ = Path(__file__).resolve().parent.parent

log = logging.getLogger(__name__)

# Quantas copias automaticas ficam no volume. Doze cobre com folga a sequencia de deploys de um dia
# ruim, e o banco inteiro hoje tem pouco mais de 100 KB; o volume tem 1 GB. O numero existe para o
# volume nao encher sozinho daqui a um ano: sem teto, backup automatico vira lixo automatico.
BACKUPS_MANTIDOS = 12
DIARIOS_MANTIDOS = 7
PREFIXO = "backup-auto-"
# Marca qual imagem ja foi vista rodando. E assim que o app sabe, sozinho, que acabou de subir uma
# versao nova, inclusive quando o deploy foi feito por fora do scripts/deploy.py.
MARCA_DA_IMAGEM = "ultima-imagem.txt"


def _config() -> Config:
    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    # Sem isso o env.py roda fileConfig e derruba o logging que o uvicorn ja montou.
    config.attributes["configurar_log"] = False
    return config


def caminho_do_banco() -> Path | None:
    """O arquivo do SQLite, ou None quando o banco nao e SQLite (Postgres um dia)."""
    if not DATABASE_URL.startswith("sqlite"):
        return None
    return Path(DATABASE_URL.split("///", 1)[1])


def revisao_atual() -> str | None:
    with engine.connect() as conexao:
        return MigrationContext.configure(conexao).get_current_revision()


def revisao_alvo() -> str | None:
    return ScriptDirectory.from_config(_config()).get_current_head()


def tem_pendencia() -> bool:
    return revisao_atual() != revisao_alvo()


def fazer_backup(origem: Path, pasta: Path, rotulo: str) -> Path:
    """Copia consistente do banco, com o WAL incluido. Levanta se o resultado nao abrir."""
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{PREFIXO}{rotulo}-{datetime.now():%Y%m%d-%H%M%S}.db"
    de = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    para = sqlite3.connect(destino)
    try:
        de.backup(para)
    finally:
        de.close()
        para.close()
    # Conferir antes de deixar a migracao seguir: backup que nao abre e o mesmo que nao existir, e
    # a hora de descobrir isso e agora, nao no dia em que ele for necessario.
    estado, contas = conferir(destino)
    if estado != "ok":
        destino.unlink(missing_ok=True)
        raise RuntimeError(f"backup de pre-migracao saiu corrompido: {estado}")
    log.warning("backup de pre-migracao gravado: %s (%s contas)", destino.name, contas)
    return destino


def conferir(arquivo: Path) -> tuple[str, int]:
    """(resultado do integrity_check, quantas contas tem dentro). Funcao propria para o teste
    conseguir simular um backup corrompido sem falsificar o sqlite3 inteiro."""
    con = sqlite3.connect(arquivo)
    try:
        return (
            con.execute("pragma integrity_check").fetchone()[0],
            con.execute("select count(*) from usuario").fetchone()[0],
        )
    finally:
        con.close()


def _limpar_antigos(pasta: Path) -> None:
    antigos = sorted(pasta.glob(f"{PREFIXO}*.db"))[:-BACKUPS_MANTIDOS]
    for arquivo in antigos:
        arquivo.unlink(missing_ok=True)


def versao_no_ar() -> str:
    """A imagem que esta rodando agora. O Fly poe isto no ambiente de toda maquina."""
    return os.getenv("FLY_IMAGE_REF") or os.getenv("FLY_MACHINE_VERSION") or ""


def _e_versao_nova(pasta: Path) -> bool:
    """True quando esta e a primeira vez que o app sobe com esta imagem.

    Existe para o backup de deploy nao depender de ninguem lembrar de rodar o script: quem publicar
    com `flyctl deploy` na mao, de madrugada e com pressa, tambem ganha a copia. Restart da mesma
    imagem (a maquina reiniciando sozinha) nao conta, senao o volume encheria de copias iguais.
    """
    versao = versao_no_ar()
    if not versao:
        return False  # dev local: nao existe imagem para comparar
    marca = pasta / MARCA_DA_IMAGEM
    anterior = marca.read_text().strip() if marca.is_file() else ""
    if anterior == versao:
        return False
    marca.write_text(versao + "\n")
    return not anterior == ""  # primeira subida de todas nao precisa de copia do banco vazio


def proteger() -> Path | None:
    """A copia automatica antes de tudo que pode estragar o banco. Devolve o arquivo, ou None.

    Dois gatilhos, e o backup sai UMA vez mesmo quando os dois acontecem juntos (o caso comum:
    deploy que traz migracao):
      - versao nova no ar, com ou sem migracao: e o instante em que codigo novo toca dado velho;
      - migracao pendente: e o instante em que o schema muda.
    Restart da mesma imagem, sem migracao, nao copia nada.
    """
    banco = caminho_do_banco()
    if banco is None or not banco.is_file():
        return None
    pendente = tem_pendencia()
    versao_nova = _e_versao_nova(banco.parent)
    if not (pendente or versao_nova):
        return None
    motivo = "deploy"
    if pendente:
        motivo = f"migracao-{revisao_atual() or 'vazio'}-para-{revisao_alvo()}"
    log.warning("copia automatica antes de %s", motivo)
    copia = fazer_backup(banco, banco.parent, motivo)
    _limpar_antigos(banco.parent)
    return copia


def atualizar() -> None:
    """Protege e migra, nessa ordem. Idempotente: sem pendencia, `upgrade` nao faz nada.

    A copia vem antes do `upgrade` e e obrigatoria: se `proteger()` levantar, a migracao nao roda,
    o app nao sobe e o Fly mantem a versao anterior. Subir sem rede seria trocar um problema
    visivel (deploy que falha) por um invisivel (dado perdido sem copia).
    """
    proteger()
    command.upgrade(_config(), "head")


def backup_diario() -> Path | None:
    """Uma copia por dia, alem do snapshot diario do volume que o Fly ja tira.

    O snapshot do Fly restaura o volume inteiro e guarda 5 dias; isto aqui e um arquivo que da para
    baixar e abrir na hora, sem restaurar nada. Sao redes diferentes, e nenhuma substitui a outra.
    """
    banco = caminho_do_banco()
    if banco is None or not banco.is_file():
        return None
    pasta = banco.parent
    hoje = f"backup-diario-{datetime.now():%Y%m%d}.db"
    if (pasta / hoje).exists():
        return None
    destino = fazer_backup(banco, pasta, "diario")
    final = pasta / hoje
    os.replace(destino, final)
    for antigo in sorted(pasta.glob("backup-diario-*.db"))[:-DIARIOS_MANTIDOS]:
        antigo.unlink(missing_ok=True)
    return final
