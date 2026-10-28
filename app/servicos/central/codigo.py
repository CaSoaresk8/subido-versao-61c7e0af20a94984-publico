import ast
import io
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

from app.config import BASE_DIR, DATA_DIR

RAIZES = {"app", "alembic", "tests", "scripts"}
ARQUIVOS = {"pyproject.toml", "uv.lock", "alembic.ini", "Dockerfile", ".gitignore"}
EXTENSOES = {
    ".py",
    ".html",
    ".css",
    ".js",
    ".json",
    ".toml",
    ".ini",
    ".svg",
    ".webp",
    ".png",
    ".jpg",
    ".mp4",
    ".lock",
    ".txt",
}
MAX_TOTAL = 60 * 1024 * 1024


def pasta(pid):
    if not re.fullmatch(r"[a-f0-9]{32}", pid):
        raise ValueError("Projeto inválido")
    return DATA_DIR / "projetos" / pid


def valido(nome):
    partes = PurePosixPath(nome).parts
    if not partes or "\\" in nome or "\x00" in nome or PurePosixPath(nome).is_absolute():
        return False
    if nome == ".gitignore":
        return True
    if any(v.startswith(".") or v == "__pycache__" for v in partes):
        return False
    return nome in ARQUIVOS or (partes[0] in RAIZES and Path(nome).suffix in EXTENSOES)


def verificar_segredos(dados):
    if re.search(
        rb"(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY",
        dados,
    ):
        raise ValueError("Possível credencial no código. Remova o segredo antes de salvar.")


def git(pid, *args):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(DATA_DIR),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
    }
    r = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Comunidade Subido",
            "-c",
            "user.email=versoes@users.noreply.github.com",
            *args,
        ],
        cwd=pasta(pid),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode:
        raise ValueError("Não foi possível registrar a revisão do código.")
    return r.stdout.strip()


def arquivos(pid):
    resultado = []
    for raiz, dirs, nomes in os.walk(pasta(pid)):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for nome in nomes:
            f = Path(raiz) / nome
            rel = f.relative_to(pasta(pid)).as_posix()
            if not f.is_symlink() and valido(rel):
                resultado.append(rel)
    return sorted(resultado)


def snapshot(pid, mensagem):
    for nome in arquivos(pid):
        verificar_segredos((pasta(pid) / nome).read_bytes())
    git(pid, "add", "--all")
    git(pid, "commit", "--allow-empty", "-m", mensagem[:160])
    return git(pid, "rev-parse", "HEAD")


def criar(pid, base_pid=None, base_sha=None):
    destino = pasta(pid)
    destino.mkdir(parents=True, exist_ok=False)
    if base_pid:
        if not base_sha or not re.fullmatch(r"[a-f0-9]{40}", base_sha):
            raise ValueError("A versão publicada não possui uma revisão confirmada.")
        with zipfile.ZipFile(io.BytesIO(exportar(base_pid, base_sha))) as pacote:
            for item in pacote.infolist():
                if item.is_dir():
                    continue
                if not valido(item.filename):
                    raise ValueError("Arquivo não permitido na versão de origem.")
                conteudo = pacote.read(item)
                verificar_segredos(conteudo)
                alvo = destino / item.filename
                alvo.parent.mkdir(parents=True, exist_ok=True)
                alvo.write_bytes(conteudo)
        git(pid, "init", "-b", "main")
        return snapshot(pid, "Cópia da revisão publicada " + base_sha[:12])
    origem = BASE_DIR.parent
    for raiz, dirs, nomes in os.walk(origem):
        rel_dir = Path(raiz).relative_to(origem)
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".")
            and d not in {"__pycache__", "data", "node_modules"}
            and (rel_dir.parts or d in RAIZES)
        ]
        for nome in nomes:
            f = Path(raiz) / nome
            rel = f.relative_to(origem).as_posix()
            if f.is_symlink() or not valido(rel):
                continue
            conteudo = f.read_bytes()
            verificar_segredos(conteudo)
            alvo = destino / rel
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(conteudo)
    git(pid, "init", "-b", "main")
    return snapshot(pid, "Versão inicial")


def editar(pid, nome, texto):
    if (
        not valido(nome)
        or Path(nome).suffix
        not in {".py", ".html", ".css", ".js", ".json", ".toml", ".ini", ".txt", ".lock"}
        or len(texto.encode()) > 1024 * 1024
    ):
        raise ValueError("Caminho ou conteúdo não permitido; limite de 1 MB.")
    verificar_segredos(texto.encode())
    alvo = pasta(pid) / nome
    if alvo.is_symlink():
        raise ValueError("Links simbólicos não são permitidos.")
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(texto)
    return snapshot(pid, "Atualiza " + nome)


def importar(pid, dados):
    if len(dados) > MAX_TOTAL:
        raise ValueError("Envie um ZIP de até 60 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as zipado:
            itens = [i for i in zipado.infolist() if not i.is_dir()]
            if not itens or len(itens) > 3000 or sum(i.file_size for i in itens) > MAX_TOTAL:
                raise ValueError("O conteúdo do ZIP excede os limites.")
            preparados = []
            for item in itens:
                if not valido(item.filename) or ((item.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError("O ZIP contém um arquivo ou caminho não permitido.")
                conteudo = zipado.read(item)
                verificar_segredos(conteudo)
                preparados.append((item.filename, conteudo))
            for nome, conteudo in preparados:
                alvo = pasta(pid) / nome
                alvo.parent.mkdir(parents=True, exist_ok=True)
                alvo.write_bytes(conteudo)
    except zipfile.BadZipFile:
        raise ValueError("ZIP inválido.") from None
    return snapshot(pid, "Importa alterações por ZIP")


def exportar(pid, revisao="HEAD"):
    if revisao != "HEAD" and not re.fullmatch(r"[a-f0-9]{40}", revisao):
        raise ValueError("Revisão inválida")
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "archive", "--format=zip", revisao],
        cwd=pasta(pid),
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout


def historico(pid):
    return [v.split("|", 2) for v in git(pid, "log", "-30", "--format=%H|%cs|%s").splitlines()]


def conferir(pid):
    total = 0
    for nome in arquivos(pid):
        conteudo = (pasta(pid) / nome).read_bytes()
        verificar_segredos(conteudo)
        total += len(conteudo)
        if nome.endswith(".py"):
            try:
                ast.parse(conteudo, filename=nome)
            except SyntaxError:
                raise ValueError("Sintaxe Python inválida em " + nome) from None
    if total > MAX_TOTAL:
        raise ValueError("O projeto excede 60 MB.")
    return git(pid, "rev-parse", "HEAD")
