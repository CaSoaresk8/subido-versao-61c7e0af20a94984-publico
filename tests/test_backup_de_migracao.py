"""O backup que roda antes de toda migracao, e o backup diario.

Isto existe porque o app migra sozinho ao subir: deploy e migracao sao o mesmo instante, com gente
usando o app. A rede de seguranca tem que ser automatica, porque a mao esquece justamente no deploy
apressado, que e quando ela faz falta.

O que estes testes garantem, e que so aparece no dia ruim:
  - com revisao pendente, o backup e feito ANTES, e contem o banco de ANTES;
  - se o backup falhar, a migracao NAO acontece;
  - restart sem pendencia nao gera copia nenhuma (senao o volume enche de arquivo igual);
  - o backup enxerga o que esta no WAL (o erro que ja me fez contar cla errado em producao);
  - o diario nao repete no mesmo dia e guarda os ultimos sete.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import esquema


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """Um banco de verdade, uma revisao atras da head, com dado dentro e WAL por fechar."""
    caminho = tmp_path / "copyecola.db"
    # O alembic/env.py le `app.config.DATABASE_URL` no instante em que roda, entao e ESTE o ponto
    # que decide qual banco a migracao toca. Sem apontar aqui, o teste migraria o banco da suite.
    monkeypatch.setattr("app.config.DATABASE_URL", f"sqlite:///{caminho}")
    anterior = _revisao_anterior()
    _subir_ate(caminho, anterior)

    con = sqlite3.connect(caminho)
    con.execute("pragma journal_mode=WAL")
    con.execute(
        "insert into usuario (nome, email, senha_hash, criado_em) values (?,?,?,?)",
        ("Fulano", "fulano@teste.local", "x", datetime.now().isoformat()),
    )
    con.commit()
    # A conexao fica ABERTA de proposito: assim o conteudo continua no -wal, que e exatamente a
    # situacao de producao (o app escrevendo enquanto o deploy acontece).
    monkeypatch.setattr(esquema, "DATABASE_URL", f"sqlite:///{caminho}")
    _apontar_engine(monkeypatch, caminho)
    yield caminho
    con.close()


def _revisao_anterior() -> str:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(esquema._config())
    head = script.get_current_head()
    return script.get_revision(head).down_revision


def _subir_ate(caminho: Path, revisao: str) -> None:
    from alembic import command

    command.upgrade(esquema._config(), revisao)


def _apontar_engine(monkeypatch, caminho: Path) -> None:
    from sqlalchemy import create_engine

    monkeypatch.setattr(esquema, "engine", create_engine(f"sqlite:///{caminho}"))


def _copias(pasta: Path) -> list[Path]:
    return sorted(pasta.glob(f"{esquema.PREFIXO}*.db"))


def test_migracao_pendente_faz_backup_antes_e_ele_tem_o_estado_anterior(banco):
    assert esquema.tem_pendencia(), "o cenario precisa de uma revisao pendente"
    antes = esquema.revisao_atual()

    esquema.atualizar()

    copias = _copias(banco.parent)
    assert len(copias) == 1, "a migracao rodou sem backup"
    copia = sqlite3.connect(copias[0])
    # O backup tem que ser de ANTES: a revisao gravada nele e a antiga.
    assert copia.execute("select version_num from alembic_version").fetchone()[0] == antes
    # E tem que conter o dado que so existia no WAL. Sem `sqlite3.backup()`, isto sai 0.
    assert copia.execute("select count(*) from usuario").fetchone()[0] == 1
    assert copia.execute("pragma integrity_check").fetchone()[0] == "ok"
    assert not esquema.tem_pendencia(), "a migracao nao chegou ao head"


def test_sem_pendencia_nenhuma_copia_e_criada(banco):
    esquema.atualizar()
    quantas = len(_copias(banco.parent))
    esquema.atualizar()
    esquema.atualizar()
    assert len(_copias(banco.parent)) == quantas, "restart normal esta gerando copia a toa"


def test_backup_que_falha_impede_a_migracao(banco, monkeypatch):
    """A regra mais importante: sem rede, nao pula. O app nem sobe, e o Fly mantem a versao velha."""

    def falhar(*_args, **_kwargs):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(esquema, "fazer_backup", falhar)
    revisao = esquema.revisao_atual()
    with pytest.raises(RuntimeError):
        esquema.atualizar()
    assert esquema.revisao_atual() == revisao, "migrou mesmo sem backup"


def test_backup_corrompido_e_recusado(banco, monkeypatch):
    """integrity_check ruim nao vira arquivo guardado: backup que nao abre e pior que nenhum."""
    monkeypatch.setattr(esquema, "conferir", lambda _a: ("falhou: pagina 3 quebrada", 0))
    with pytest.raises(RuntimeError, match="corrompido"):
        esquema.fazer_backup(banco, banco.parent, "teste")
    assert not _copias(banco.parent), "o arquivo corrompido ficou para tras"


def test_conferir_le_o_arquivo_de_verdade(banco):
    """Sem isto, o teste de cima estaria simulando uma funcao que ninguem provou que funciona."""
    copia = esquema.fazer_backup(banco, banco.parent, "teste")
    assert esquema.conferir(copia) == ("ok", 1)


def test_so_os_ultimos_dez_backups_ficam(banco):
    pasta = banco.parent
    for i in range(14):
        (pasta / f"{esquema.PREFIXO}velho-{i:02d}.db").write_bytes(b"")
    esquema._limpar_antigos(pasta)
    assert len(_copias(pasta)) == esquema.BACKUPS_MANTIDOS


def test_backup_diario_nao_repete_no_mesmo_dia_e_guarda_sete(banco):
    primeiro = esquema.backup_diario()
    assert primeiro is not None and primeiro.exists()
    assert esquema.backup_diario() is None, "fez dois backups diarios no mesmo dia"

    pasta = banco.parent
    for dias in range(1, 12):
        dia = (datetime.now() - timedelta(days=dias)).strftime("%Y%m%d")
        (pasta / f"backup-diario-{dia}.db").write_bytes(b"")
    (pasta / primeiro.name).unlink()
    esquema.backup_diario()
    assert len(sorted(pasta.glob("backup-diario-*.db"))) == 7


# ---------------------------------------------------------------------------------------------
# A copia por VERSAO NOVA: protege tambem quem publicar sem passar pelo scripts/deploy.py
# ---------------------------------------------------------------------------------------------


def test_versao_nova_sem_migracao_faz_copia(banco, monkeypatch):
    esquema.atualizar()  # chega no head; daqui em diante nao ha migracao pendente
    (banco.parent / esquema.MARCA_DA_IMAGEM).write_text("imagem-antiga\n")
    antes = len(_copias(banco.parent))

    monkeypatch.setenv("FLY_IMAGE_REF", "registry.fly.io/app:deployment-nova")
    copia = esquema.proteger()

    assert copia is not None, "deploy sem migracao passou sem copia"
    assert len(_copias(banco.parent)) == antes + 1
    assert "deploy" in copia.name
    assert (banco.parent / esquema.MARCA_DA_IMAGEM).read_text().strip().endswith("deployment-nova")


def test_restart_da_mesma_versao_nao_copia(banco, monkeypatch):
    esquema.atualizar()
    monkeypatch.setenv("FLY_IMAGE_REF", "registry.fly.io/app:deployment-1")
    esquema.proteger()  # primeira vez com esta imagem
    quantas = len(_copias(banco.parent))

    for _ in range(3):  # a maquina reiniciando sozinha, varias vezes
        assert esquema.proteger() is None
    assert len(_copias(banco.parent)) == quantas, "restart esta enchendo o volume de copia igual"


def test_deploy_com_migracao_gera_uma_copia_so(banco, monkeypatch):
    """O caso comum. Duas copias do mesmo instante seriam ruido, e ruido esconde a copia util."""
    monkeypatch.setenv("FLY_IMAGE_REF", "registry.fly.io/app:deployment-com-migracao")
    (banco.parent / esquema.MARCA_DA_IMAGEM).write_text("imagem-antiga\n")

    esquema.atualizar()

    copias = _copias(banco.parent)
    assert len(copias) == 1, f"saiu mais de uma copia: {[c.name for c in copias]}"
    # E a copia certa: a que sabe de qual revisao para qual, que e a informacao que serve no dia
    # em que alguem precisar restaurar.
    assert "migracao" in copias[0].name


def test_sem_fly_image_ref_nada_de_copia_por_versao(banco):
    """No dev local nao existe imagem: rodar o app na maquina de casa nao pode gerar backup."""
    esquema.atualizar()
    assert esquema.versao_no_ar() == ""
    assert esquema.proteger() is None
