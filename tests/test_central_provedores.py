import uuid
from pydantic import SecretStr


def test_proposta_preserva_arquivos_originais(ana, monkeypatch):
    from app.servicos.central import codigo, provedores

    pid = uuid.uuid4().hex
    sha = codigo.criar(pid)
    codigo.editar(pid, "app/melhoria.py", "MELHORIA = True\n")
    chamadas = []

    def github(token, metodo, caminho, dados=None):
        chamadas.append((metodo, caminho, dados))
        if caminho.endswith("/git/trees"):
            assert dados["base_tree"] == "arvore-original"
            assert [f["path"] for f in dados["tree"]] == ["app/melhoria.py"]
        if metodo == "GET" and caminho.endswith("copy-e-cola"):
            return {"default_branch": "main"}
        if "/git/ref/" in caminho:
            return {"object": {"sha": "pai"}}
        if "/git/commits/pai" in caminho:
            return {"tree": {"sha": "arvore-original"}}
        return {"sha": "a" * 40, "html_url": "https://github.com/exemplo/proposta"}

    monkeypatch.setattr(provedores, "github", github)
    resultado = provedores.propor(
        pid,
        SecretStr("ficticio"),
        "CaSoaresk8",
        {"inicial_sha": sha},
        "Melhoria",
        "Proposta de teste",
    )
    assert resultado.endswith("proposta")
    assert chamadas[-1][2]["draft"] is True


def test_implantacao_isola_codigo_dados_e_credenciais(ana, monkeypatch):
    from pathlib import Path
    from app.servicos.central import codigo, provedores

    pid = uuid.uuid4().hex
    codigo.criar(pid)
    chamadas = []

    def fly(token, args, cwd=None, entrada=None, timeout=90):
        chamadas.append(args)
        assert "segredo-ficticio" not in " ".join(args)
        if args[:2] == ["apps", "list"]:
            return "[]"
        if args[:2] == ["ips", "list"]:
            return "[]"
        if args[:2] == ["volumes", "list"]:
            return "[]"
        if args[0] == "deploy":
            pasta = Path(cwd)
            assert not (pasta / ".env").exists()
            assert not (pasta / ".git").exists()
            assert not (pasta / "data").exists()
            texto = (pasta / "fly.toml").read_text()
            assert 'AGENDA_ATIVA = "0"' in texto
            assert "min_machines_running = 0" in texto
            assert '"uvicorn"' in (pasta / "Dockerfile").read_text()
        return "{}"

    class Resposta:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(provedores, "fly", fly)
    monkeypatch.setattr(provedores.urllib.request, "urlopen", lambda *a, **kw: Resposta())
    config = provedores.implantar(pid, SecretStr("segredo-ficticio"), "org-teste", {}, previa=True)
    assert config["previa_sha"] == codigo.git(pid, "rev-parse", "HEAD")
    assert any("--network" in a for a in chamadas)
    assert any("--shared" in a for a in chamadas)
