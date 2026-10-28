import base64
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile

from pydantic import SecretStr

from app.config import DATA_DIR
from app.servicos.central import codigo

FLY = os.environ.get("CENTRAL_FLYCTL", str(Path.home() / ".fly/bin/flyctl"))


class IntegracaoErro(ValueError):
    def __init__(self, mensagem, status=None):
        super().__init__(mensagem)
        self.status = status


def github(token: SecretStr, metodo, caminho, dados=None):
    if not caminho.startswith("/") or caminho.startswith("//"):
        raise IntegracaoErro("Caminho GitHub inválido")
    body = json.dumps(dados).encode() if dados is not None else None
    req = urllib.request.Request(
        "https://api.github.com" + caminho,
        data=body,
        method=metodo,
        headers={
            "Authorization": "Bearer " + token.get_secret_value(),
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "Subido-Central",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read(4 * 1024 * 1024)
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise IntegracaoErro(
            f"GitHub recusou a operação (HTTP {e.code}). Confira permissões, existência do repositório e autorização.",
            status=e.code,
        ) from None
    except (OSError, ValueError):
        raise IntegracaoErro("Não foi possível consultar o GitHub agora.") from None


def fly(token: SecretStr, args, cwd=None, entrada=None, timeout=90):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(DATA_DIR / "fly-home"),
        "FLY_API_TOKEN": token.get_secret_value(),
        "NO_COLOR": "1",
        "TERM": "dumb",
        "FLYCTL_NO_UPDATE_CHECK": "1",
    }
    try:
        r = subprocess.run(
            [FLY, *args], cwd=cwd, env=env, input=entrada, capture_output=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        raise IntegracaoErro(
            "Fly.io indisponível ou operação excedeu o tempo. Confira a tarefa antes de tentar novamente."
        ) from None
    if r.returncode:
        raise IntegracaoErro(
            "Fly.io recusou a operação. Confira permissões do token, cobrança ativa e os recursos no painel do Fly.io."
        )
    return r.stdout.decode(errors="replace")


def validar_conexao(provedor, token: SecretStr, organizacao=""):
    if provedor == "github":
        conta = github(token, "GET", "/user")
        login = conta.get("login", "")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
            raise IntegracaoErro("Identidade GitHub não confirmada.")
        if login == "bz-caio":
            raise IntegracaoErro(
                "A conta corporativa exige autorização específica. Use a conta pessoal nesta validação."
            )
        return login
    if provedor == "fly":
        if not re.fullmatch(r"[a-z0-9-]{1,80}", organizacao):
            raise IntegracaoErro("Informe o identificador da organização Fly.io.")
        json.loads(fly(token, ["apps", "list", "--org", organizacao, "--json"]))
        return organizacao
    raise IntegracaoErro("Provedor inválido")


def nome_repo(pid):
    return "subido-versao-" + pid[:16]


def sincronizar(pid, token, login, config, publico=False):
    campo = "github_publico_repo" if publico else "github_repo"
    repo = config.get(campo)
    if not repo:
        nome = nome_repo(pid) + ("-publico" if publico else "")
        try:
            novo = github(token, "GET", "/repos/" + login + "/" + nome)
        except IntegracaoErro as erro:
            if erro.status != 404:
                raise
            novo = github(
                token,
                "POST",
                "/user/repos",
                {
                    "name": nome,
                    "private": True,
                    "auto_init": False,
                    "description": "Versão independente criada pela Central Subido Clã",
                },
            )
        if not publico and not novo.get("private"):
            raise IntegracaoErro(
                "O repositório de trabalho deve ser privado para proteger os rascunhos."
            )
        repo = novo["full_name"]
        config[campo] = repo
    if not re.fullmatch(re.escape(login) + r"/[A-Za-z0-9_.-]+", repo):
        raise IntegracaoErro("O repositório não corresponde à conta conectada.")
    codigo.conferir(pid)
    credencial = base64.b64encode(("x-access-token:" + token.get_secret_value()).encode()).decode()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(DATA_DIR),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + credencial,
    }
    r = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "credential.helper=",
            "push",
            "https://github.com/" + repo + ".git",
            "HEAD:refs/heads/main",
        ],
        cwd=codigo.pasta(pid),
        env=env,
        capture_output=True,
        timeout=180,
    )
    if r.returncode:
        raise IntegracaoErro(
            "O envio do código ao GitHub falhou. Confira o repositório e tente sincronizar novamente."
        )
    config["github_sha"] = codigo.git(pid, "rev-parse", "HEAD")
    return config


def propor(pid, token, login, config, titulo, descricao):
    upstream = config.get("upstream", "CaSoaresk8/copy-e-cola")
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", upstream):
        raise IntegracaoErro("Repositório de origem inválido.")
    origem = github(token, "GET", "/repos/" + upstream)
    branch = origem["default_branch"]
    ref = github(token, "GET", "/repos/" + upstream + "/git/ref/heads/" + branch)
    parent = ref["object"]["sha"]
    destino = upstream
    if login != upstream.split("/")[0]:
        fork = github(token, "POST", "/repos/" + upstream + "/forks", {"default_branch_only": True})
        destino = fork["full_name"]
    codigo.conferir(pid)
    inicial = config.get("inicial_sha")
    if not inicial or not re.fullmatch(r"[a-f0-9]{40}", inicial):
        raise IntegracaoErro("Revisão inicial ausente; não é seguro preparar a proposta.")
    alterados = codigo.git(pid, "diff", "--name-only", inicial, "HEAD").splitlines()
    if not alterados:
        raise IntegracaoErro("Altere o código antes de propor uma melhoria.")
    base_commit = github(token, "GET", "/repos/" + upstream + "/git/commits/" + parent)
    arvore = []
    for nome in alterados:
        if not codigo.valido(nome):
            raise IntegracaoErro("Caminho não permitido na proposta.")
        if not (codigo.pasta(pid) / nome).exists():
            arvore.append({"path": nome, "mode": "100644", "type": "blob", "sha": None})
            continue
        dados = (codigo.pasta(pid) / nome).read_bytes()
        codigo.verificar_segredos(dados)
        blob = github(
            token,
            "POST",
            "/repos/" + destino + "/git/blobs",
            {"content": base64.b64encode(dados).decode(), "encoding": "base64"},
        )
        arvore.append({"path": nome, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree = github(
        token,
        "POST",
        "/repos/" + destino + "/git/trees",
        {"base_tree": base_commit["tree"]["sha"], "tree": arvore},
    )
    commit = github(
        token,
        "POST",
        "/repos/" + destino + "/git/commits",
        {"message": titulo, "tree": tree["sha"], "parents": [parent]},
    )
    nome_branch = "central/" + pid + "-" + commit["sha"][:8]
    github(
        token,
        "POST",
        "/repos/" + destino + "/git/refs",
        {"ref": "refs/heads/" + nome_branch, "sha": commit["sha"]},
    )
    return github(
        token,
        "POST",
        "/repos/" + upstream + "/pulls",
        {
            "title": titulo,
            "body": descricao,
            "base": branch,
            "head": login + ":" + nome_branch,
            "draft": True,
        },
    )["html_url"]


DOCKERFILE = """FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app PRODUCAO=1 DATA_DIR=/data CENTRAL_ATIVA=0
EXPOSE 8080
CMD [\"uvicorn\",\"app.main:app\",\"--host\",\"0.0.0.0\",\"--port\",\"8080\",\"--proxy-headers\",\"--forwarded-allow-ips\",\"*\"]
"""


def implantar(
    pid, token, organizacao, config, previa=False, checkpoint=lambda: None, vitrine=False
):
    revisao = codigo.conferir(pid)
    modo = "vitrine" if vitrine else ("previa" if previa else "publicacao")
    appname = config.get(modo + "_app") or "subido-" + pid[:16] + (
        "-vitrine" if vitrine else ("-demo" if previa else "")
    )
    apps = json.loads(fly(token, ["apps", "list", "--org", organizacao, "--json"]))
    if not isinstance(apps, list):
        raise IntegracaoErro("O Fly.io não retornou a lista esperada de aplicações.")
    existentes = {a.get("Name", a.get("name")) for a in apps}
    if appname not in existentes:
        fly(token, ["apps", "create", appname, "--org", organizacao, "--network", appname])
    config[modo + "_app"] = appname
    checkpoint()
    ips = json.loads(fly(token, ["ips", "list", "-a", appname, "--json"]))
    tipos = {i.get("Type", i.get("type")) for i in ips}
    if not tipos.intersection({"v4", "shared_v4"}):
        fly(token, ["ips", "allocate-v4", "--shared", "-a", appname])
    if "v6" not in tipos:
        fly(token, ["ips", "allocate-v6", "-a", appname])
    volumes = json.loads(fly(token, ["volumes", "list", "-a", appname, "--json"]))
    if not any(v.get("Name", v.get("name")) == "dados" for v in volumes):
        fly(
            token,
            [
                "volumes",
                "create",
                "dados",
                "--region",
                "gru",
                "--size",
                "1",
                "-a",
                appname,
                "--yes",
            ],
        )
    if modo + "_key" not in config:
        # Esta chave fica cifrada com as conexoes, nunca no codigo-fonte.
        config[modo + "_key"] = secrets.token_urlsafe(48)
    chave = config[modo + "_key"]
    checkpoint()
    entrada = (
        "SECRET_KEY="
        + chave
        + "\nCENTRAL_ATIVA=0\nURL_PUBLICA=https://"
        + appname
        + ".fly.dev\nDEMO_MODO="
        + ("1" if previa or vitrine else "0")
        + "\nDEMO_AUDIENCIA="
        + pid
        + "\nDEMO_CHAVE="
        + chave
        + "\n"
    ).encode()
    fly(token, ["secrets", "import", "-a", appname, "--stage"], entrada=entrada)
    with tempfile.TemporaryDirectory(prefix="subido-build-") as td:
        destino = Path(td)
        with zipfile.ZipFile(io.BytesIO(codigo.exportar(pid, revisao))) as z:
            z.extractall(destino)
        (destino / "Dockerfile").write_text(DOCKERFILE)
        (destino / ".dockerignore").write_text(".git\n.env*\ndata\n.venv\n.local-review\n")
        (destino / "fly.toml").write_text(f'''app = "{appname}"
primary_region = "gru"
[env]
PRODUCAO = "1"
DATA_DIR = "/data"
CENTRAL_ATIVA = "0"
AGENDA_ATIVA = "0"
[[mounts]]
source = "dados"
destination = "/data"
[http_service]
internal_port = 8080
force_https = true
auto_stop_machines = "stop"
auto_start_machines = true
min_machines_running = 0
[[http_service.checks]]
grace_period = "15s"
interval = "30s"
method = "GET"
path = "/login"
timeout = "5s"
[[vm]]
size = "shared-cpu-1x"
memory = "512mb"
''')
        fly(token, ["deploy", "--remote-only", "--ha=false", "-a", appname], cwd=td, timeout=900)
    url = "https://" + appname + ".fly.dev"
    try:
        with urllib.request.urlopen(url + "/login", timeout=30) as resposta:
            if resposta.status != 200:
                raise OSError()
    except OSError:
        raise IntegracaoErro(
            "Publicação enviada, mas a verificação de saúde falhou. Confira o app antes de repetir."
        ) from None
    config[modo + "_url"] = url
    config[modo + "_sha"] = revisao
    return config


def dominio(token, appname, host, criar=False):
    if not re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host
    ):
        raise IntegracaoErro("Informe apenas um domínio válido, sem https ou caminhos.")
    if criar:
        fly(token, ["certs", "add", host, "-a", appname, "--json"])
    return json.loads(fly(token, ["certs", "check", host, "-a", appname, "--json"]))
