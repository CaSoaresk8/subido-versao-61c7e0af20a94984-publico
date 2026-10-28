"""O deploy do Subido Cla, com as travas que a plataforma passou a exigir quando ganhou gente.

Roda no Ubuntu do Caio:

    python scripts/deploy.py            # deploy protegido, do inicio ao fim
    python scripts/deploy.py --conferir # so olha producao, nao muda nada
    python scripts/deploy.py --voltar   # volta para a imagem anterior (rollback)

A ordem existe por motivos, e nenhum deles e burocracia:

1. **Testes primeiro.** Deploy comeca no que da para saber antes de mexer em producao.
2. **Medir o movimento.** Deploy reinicia a unica maquina, e existe uma janela de segundos em que o
   app nao responde. Com gente entrando a cada minuto, alguem perde o formulario. O script conta os
   cadastros e as acoes dos ultimos 15 minutos e pede confirmacao quando esta movimentado.
3. **Backup completo, baixado e aberto.** Feito com `sqlite3.backup()` DENTRO da maquina: o banco
   esta em modo WAL, e copiar so o arquivo .db traz um banco velho que parece inteiro. O arquivo e
   baixado para ~/backups-copyecola e aberto aqui antes de o deploy comecar.
4. **Guardar a imagem atual.** E o unico jeito de voltar em um comando. Fica em
   ~/backups-copyecola/ultima-imagem.txt.
5. **Fotografar as contagens.** Quantos clas, contas, membros, missoes, entregas, eventos.
6. **Deploy.**
7. **Conferir depois:** rotas respondendo, nenhuma contagem menor do que antes (o app so cresce
   nessas tabelas; diminuir e sinal de migracao que comeu dado), e log sem excecao nova.

Se qualquer passo falhar, o script para e imprime o comando de volta. Ele nunca volta sozinho: o
rollback tambem reinicia a maquina, e decidir isso e do Caio.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP = "cla-copyecola"
URL = "https://cla.ialabor.com"
BANCO = "/data/copyecola.db"
DESTINO = Path.home() / "backups-copyecola"
ARQUIVO_IMAGEM = DESTINO / "ultima-imagem.txt"
FLYCTL = Path.home() / ".fly" / "bin" / "flyctl"
RAIZ = Path(__file__).resolve().parent.parent

# Acima disso o app esta em uso pesado e o deploy pede confirmacao.
MOVIMENTO_ALTO = 3
# Quantas copias ficam aqui na maquina. O volume do servidor ja guarda as automaticas (12 antes de
# deploy/migracao e 7 diarias); estas sao a terceira rede, a que sobrevive ao servidor sumir. Teto
# porque backup sem teto vira pasta de 40 GB que ninguem olha.
BACKUPS_LOCAIS = 10
TABELAS = ("cla", "usuario", "membro", "missao", "entrega", "tarefa_pessoal", "coluna", "log")


def token() -> str:
    """O token do Fly, lido do config local. Nunca impresso, nunca passado em linha de comando
    (argumento aparece no `ps` de qualquer processo da maquina)."""
    config = (Path.home() / ".fly" / "config.yml").read_text()
    achado = re.search(r"^access_token:\s*(.+)$", config, re.M)
    if not achado:
        sys.exit("FALHOU: nao achei o access_token em ~/.fly/config.yml. Rode: flyctl auth login")
    return achado.group(1).strip()


def fly(*args: str, capturar: bool = True) -> str:
    import os

    ambiente = {**os.environ, "FLY_API_TOKEN": token()}
    processo = subprocess.run(
        [str(FLYCTL), *args],
        env=ambiente,
        text=True,
        capture_output=capturar,
        check=False,
    )
    if processo.returncode != 0:
        saida = (processo.stdout or "") + (processo.stderr or "") if capturar else ""
        sys.exit(f"FALHOU: flyctl {' '.join(args)}\n{saida.strip()[-2000:]}")
    return processo.stdout if capturar else ""


def na_maquina(codigo: str) -> str:
    """Roda um trecho de Python dentro da maquina de producao.

    Vai em base64 porque o comando passa por duas camadas de shell (a local e a de la), e aspas
    dentro de aspas e o tipo de detalhe que quebra em silencio no dia errado.
    """
    import base64

    pacote = base64.b64encode(codigo.encode()).decode()
    return fly("ssh", "console", "-a", APP, "-C", f"sh -c 'echo {pacote} | base64 -d | python'")


def contagens() -> dict[str, int]:
    saida = na_maquina(
        "import sqlite3, json\n"
        f"c = sqlite3.connect('file:{BANCO}?mode=ro', uri=True)\n"
        "tabs = " + repr(list(TABELAS)) + "\n"
        "existe = {r[0] for r in c.execute(\"select name from sqlite_master where type='table'\")}\n"
        "print('CONTAGENS', json.dumps({t: c.execute(f'select count(*) from {t}').fetchone()[0]"
        " for t in tabs if t in existe}))"
    )
    achado = re.search(r"CONTAGENS (\{.*\})", saida)
    if not achado:
        sys.exit(f"FALHOU: nao consegui ler as contagens de producao.\n{saida[-800:]}")
    import json

    return json.loads(achado.group(1))


def movimento() -> int:
    """Quantas pessoas mexeram no app nos ultimos 15 minutos (o log guarda UTC)."""
    corte = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M")
    saida = na_maquina(
        "import sqlite3\n"
        f"c = sqlite3.connect('file:{BANCO}?mode=ro', uri=True)\n"
        f"print('MOVIMENTO', c.execute(\"select count(*) from log where criado_em > '{corte}'\")"
        ".fetchone()[0])"
    )
    achado = re.search(r"MOVIMENTO (\d+)", saida)
    return int(achado.group(1)) if achado else 0


def imagem_atual() -> str:
    saida = fly("status", "-a", APP)
    achado = re.search(r"(registry\.fly\.io/\S+|cla-copyecola:deployment-\S+)", saida)
    if not achado:
        sys.exit("FALHOU: nao consegui descobrir a imagem que esta no ar.")
    imagem = achado.group(1)
    return imagem if imagem.startswith("registry") else f"registry.fly.io/{imagem}"


def backup() -> Path:
    DESTINO.mkdir(parents=True, exist_ok=True)
    nome = f"backup-{datetime.now():%Y%m%d-%H%M}.db"
    print(f"  fazendo backup em producao ({nome})")
    saida = na_maquina(
        "import sqlite3\n"
        f"de = sqlite3.connect('file:{BANCO}?mode=ro', uri=True)\n"
        f"para = sqlite3.connect('/data/{nome}')\n"
        "de.backup(para)\n"
        "print('BACKUP', para.execute('pragma integrity_check').fetchone()[0],"
        " para.execute('select count(*) from usuario').fetchone()[0])"
    )
    if "BACKUP ok" not in saida:
        sys.exit(f"FALHOU: o backup em producao nao saiu integro.\n{saida[-800:]}")
    print("  baixando")
    fly("ssh", "sftp", "get", "-a", APP, f"/data/{nome}", str(DESTINO / nome), capturar=False)
    local = DESTINO / nome
    if not local.is_file() or local.stat().st_size < 20_000:
        sys.exit(f"FALHOU: o backup baixado esta vazio ou pequeno demais: {local}")
    import sqlite3

    con = sqlite3.connect(local)
    estado = con.execute("pragma integrity_check").fetchone()[0]
    contas = con.execute("select count(*) from usuario").fetchone()[0]
    con.close()
    if estado != "ok":
        sys.exit(f"FALHOU: o backup baixado nao abre ({estado}).")
    print(f"  backup conferido aqui: {local} ({contas} contas)")
    _limpar_locais()
    return local


def _limpar_locais() -> None:
    copias = sorted(DESTINO.glob("backup-*.db"), key=lambda a: a.stat().st_mtime)
    for antigo in copias[:-BACKUPS_LOCAIS]:
        antigo.unlink(missing_ok=True)
        print(f"  (apaguei a copia antiga {antigo.name})")


def rotas_respondem() -> bool:
    import urllib.error
    import urllib.request

    tudo_bem = True
    for caminho in ("/login", "/criar-cla", "/privacidade", "/termos"):
        try:
            with urllib.request.urlopen(URL + caminho, timeout=15) as resposta:
                codigo = resposta.status
        except urllib.error.HTTPError as erro:
            codigo = erro.code
        except Exception as erro:  # noqa: BLE001
            print(f"  {caminho}: NAO RESPONDEU ({erro})")
            tudo_bem = False
            continue
        print(f"  {caminho}: {codigo}")
        tudo_bem = tudo_bem and codigo == 200
    return tudo_bem


def conferir(antes: dict[str, int] | None = None) -> bool:
    print("\nConferindo producao")
    ok = rotas_respondem()
    depois = contagens()
    print(f"  contagens: {depois}")
    if antes:
        for tabela, quanto in antes.items():
            if depois.get(tabela, 0) < quanto:
                print(f"  ALERTA: {tabela} caiu de {quanto} para {depois.get(tabela)}")
                ok = False
    erros = fly("logs", "-a", APP, "--no-tail")
    suspeitas = [
        linha
        for linha in erros.splitlines()
        if re.search(r"Traceback|ERROR|Internal Server Error", linha)
    ]
    print(f"  linhas de erro no log recente: {len(suspeitas)}")
    for linha in suspeitas[:5]:
        print(f"    {linha[-160:]}")
    return ok and not suspeitas


def testes() -> None:
    print("Rodando a suite de testes")
    processo = subprocess.run(
        ["uv", "run", "pytest", "-q"], cwd=RAIZ, text=True, capture_output=True, check=False
    )
    ultima = (processo.stdout or "").strip().splitlines()[-1:] or [""]
    print(f"  {ultima[0]}")
    if processo.returncode != 0:
        sys.exit("FALHOU: teste vermelho. Deploy cancelado.")


def confirmar(pergunta: str) -> None:
    if input(f"{pergunta} [s/N] ").strip().lower() not in ("s", "sim"):
        sys.exit("Cancelado.")


def deploy() -> None:
    testes()

    print("\nOlhando o movimento em producao")
    acoes = movimento()
    print(f"  {acoes} acoes nos ultimos 15 minutos")
    if acoes > MOVIMENTO_ALTO:
        print("  O app esta em uso agora. O deploy derruba a maquina por alguns segundos.")
        confirmar("  Continuar mesmo assim?")

    print("\nBackup")
    backup()

    anterior = imagem_atual()
    ARQUIVO_IMAGEM.write_text(anterior + "\n")
    print(f"\nImagem que esta no ar (guardada para voltar): {anterior}")

    antes = contagens()
    print(f"Contagens antes: {antes}")

    print("\nPublicando")
    subprocess.run(
        [str(FLYCTL), "deploy", "--remote-only", "-a", APP],
        cwd=RAIZ,
        check=True,
        env={**__import__("os").environ, "FLY_API_TOKEN": token()},
    )

    if conferir(antes):
        print("\nDEPLOY OK.")
    else:
        print("\nALGO NAO BATE DEPOIS DO DEPLOY.")
        print(f"Para voltar:  python scripts/deploy.py --voltar    (imagem {anterior})")
        print(f"O backup de antes esta em {DESTINO}")
        sys.exit(1)


def voltar() -> None:
    if not ARQUIVO_IMAGEM.is_file():
        sys.exit(f"FALHOU: nao sei para qual imagem voltar ({ARQUIVO_IMAGEM} nao existe).")
    imagem = ARQUIVO_IMAGEM.read_text().strip()
    print(f"Voltar para {imagem}")
    print(
        "Isso reinicia a maquina. O BANCO NAO volta: se a migracao mudou dado, restaure o backup."
    )
    confirmar("Continuar?")
    fly("deploy", "--image", imagem, "-a", APP, capturar=False)
    conferir()


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy protegido do Subido Cla")
    parser.add_argument("--conferir", action="store_true", help="so olha producao")
    parser.add_argument("--voltar", action="store_true", help="volta para a imagem anterior")
    opcoes = parser.parse_args()
    if opcoes.conferir:
        sys.exit(0 if conferir() else 1)
    if opcoes.voltar:
        voltar()
        return
    deploy()


if __name__ == "__main__":
    main()
