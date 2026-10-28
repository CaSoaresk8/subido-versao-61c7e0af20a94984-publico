import io
import zipfile

import pytest
from sqlalchemy import delete

from app.models import ProjetoVersao, TarefaCentral


def test_criar_editar_exportar_e_isolar(ana, carla):
    from app.database import SessionLocal
    from app.servicos.central import codigo, fluxo

    res = ana.post(
        "/versoes/criar", data={"nome": "Versão integrada de teste"}, follow_redirects=False
    )
    assert res.status_code == 303
    url = res.headers["location"]
    pid = url.rsplit("/", 1)[-1]
    try:
        assert carla.get(url).status_code == 404
        assert carla.get(url + "/estado").status_code == 404
        assert ana.get(url).status_code == 200
        assert fluxo.processar_um()
        pagina = ana.get(url)
        assert pagina.status_code == 200
        assert "Salvar revisão" in pagina.text
        estado = ana.get(url + "/estado").json()
        assert not estado["ocupada"] and estado["tarefas"][0]["estado"] == "concluida", estado
        inicial = codigo.git(pid, "rev-parse", "HEAD")
        res = ana.post(
            url + "/editar",
            data={"arquivo": "app/central_teste.py", "texto": "VALOR = 42\n"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        assert codigo.git(pid, "rev-parse", "HEAD") != inicial
        assert (
            carla.post(
                url + "/editar", data={"arquivo": "app/central_teste.py", "texto": "errado"}
            ).status_code
            == 404
        )
        assert (
            "erro="
            in ana.post(
                url + "/editar",
                data={"arquivo": "../fora.py", "texto": "x"},
                follow_redirects=False,
            ).headers["location"]
        )
        assert (
            ana.post(
                url + "/editar",
                data={"arquivo": "app/x.py", "texto": "x"},
                headers={"origin": "https://outro.example"},
            ).status_code
            == 403
        )
        pacote = ana.get(url + "/codigo.zip")
        assert pacote.status_code == 200
        with zipfile.ZipFile(io.BytesIO(pacote.content)) as z:
            assert z.read("app/central_teste.py") == b"VALOR = 42\n"
            assert not any(
                ".env" in f or f.endswith(".db") or f.startswith(".local-review")
                for f in z.namelist()
            )
        res = ana.post(url + "/acao", data={"acao": "conferir"}, follow_redirects=False)
        assert res.status_code == 303 and fluxo.processar_um()
        assert ana.get(url + "/estado").json()["tarefas"][0]["estado"] == "concluida"
        # Nenhuma integração externa é chamada sem confirmação.
        assert (
            "erro="
            in ana.post(url + "/acao", data={"acao": "previa"}, follow_redirects=False).headers[
                "location"
            ]
        )
    finally:
        with SessionLocal() as db:
            db.execute(delete(TarefaCentral).where(TarefaCentral.projeto_id == pid))
            db.execute(delete(ProjetoVersao).where(ProjetoVersao.id == pid))
            db.commit()


def test_copia_usa_revisao_publicada_e_zip_bloqueia_travessia(ana):
    import uuid
    from app.servicos.central import codigo

    original, copia = uuid.uuid4().hex, uuid.uuid4().hex
    sha = codigo.criar(original)
    codigo.editar(original, "app/privado.py", "PRIVADO = True\n")
    codigo.criar(copia, original, sha)
    assert not (codigo.pasta(copia) / "app/privado.py").exists()
    pacote = io.BytesIO()
    with zipfile.ZipFile(pacote, "w") as z:
        z.writestr("../escape.py", "x")
    with pytest.raises(ValueError):
        codigo.importar(copia, pacote.getvalue())


def test_cofre_nao_persiste_token_aberto(ana):
    from app.servicos.central import cofre

    valor = "credencial-ficticia-apenas-teste"
    c = cofre.Credencial(token=valor)
    assert valor not in repr(c)
    cifrado = cofre.cifrar(c)
    assert valor not in cifrado
    assert cofre.abrir(cifrado).get_secret_value() == valor


def test_demonstracao_nao_aceita_payload_invalido(visitante, monkeypatch):
    from itsdangerous import URLSafeTimedSerializer

    chave = "chave-ficticia-de-teste-com-mais-de-32-caracteres"
    monkeypatch.setenv("DEMO_MODO", "1")
    monkeypatch.setenv("DEMO_CHAVE", chave)
    monkeypatch.setenv("DEMO_AUDIENCIA", "audiencia-teste")
    assinar = URLSafeTimedSerializer(chave, salt="subido-demo")
    for payload in (
        [],
        {"aud": "outra", "nonce": "a" * 64},
        {"aud": "audiencia-teste", "nonce": 1},
    ):
        assert (
            visitante.post(
                "/demonstracao/entrar", data={"codigo": assinar.dumps(payload)}
            ).status_code
            == 403
        )


def test_demonstracao_entra_logada_isolada_e_nao_reutiliza_codigo(app_web, ana, monkeypatch):
    import secrets
    from fastapi.testclient import TestClient
    from itsdangerous import URLSafeTimedSerializer
    from app.database import SessionLocal
    from app.models import Cla, Membro, Missao, Usuario
    from sqlalchemy import select

    chave = "chave-ficticia-de-demo-com-mais-de-32-caracteres"
    monkeypatch.setenv("DEMO_MODO", "1")
    monkeypatch.setenv("DEMO_CHAVE", chave)
    monkeypatch.setenv("DEMO_AUDIENCIA", "demo-isolada")
    acesso = URLSafeTimedSerializer(chave, salt="subido-demo").dumps(
        {"aud": "demo-isolada", "nonce": secrets.token_hex(32)}
    )
    cliente = TestClient(app_web)
    uid = cid = None
    try:
        resposta = cliente.post(
            "/demonstracao/entrar", data={"codigo": acesso}, follow_redirects=False
        )
        assert resposta.status_code == 303
        tela = cliente.get("/")
        assert tela.status_code == 200
        assert "Experimente sua primeira missão" in tela.text
        assert "Cla de Teste" not in tela.text
        assert "Experimente sua primeira missão" not in ana.get("/").text
        assert cliente.post("/demonstracao/entrar", data={"codigo": acesso}).status_code == 403
        with SessionLocal() as db:
            pessoa = db.scalar(select(Usuario).where(Usuario.email.like("demo-%@exemplo.invalid")))
            assert pessoa is not None
            uid = pessoa.id
            cid = db.scalar(select(Membro.cla_id).where(Membro.usuario_id == uid))
    finally:
        if uid is not None:
            with SessionLocal() as db:
                db.execute(delete(Missao).where(Missao.cla_id == cid))
                db.execute(delete(Membro).where(Membro.usuario_id == uid))
                db.execute(delete(Cla).where(Cla.id == cid))
                db.execute(delete(Usuario).where(Usuario.id == uid))
                db.commit()
