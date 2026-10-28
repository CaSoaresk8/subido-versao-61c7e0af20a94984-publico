from sqlalchemy import delete

from app.models import VersaoComunidade


def test_biblioteca_exige_login(visitante):
    assert visitante.get("/versoes", follow_redirects=False).status_code == 303
    assert visitante.post("/versoes/importar", follow_redirects=False).status_code == 303


def test_publicacao_persistencia_busca_e_leitura_publica(ana, carla):
    from app.database import SessionLocal

    dados = {
        "nome": "Versao teste central z91",
        "numero": "1.0.0",
        "resumo": "Busca de novidades z91",
        "novidades": "Melhoria registrada",
        "categoria": "produtividade",
        "repositorio": "https://github.com/exemplo/projeto",
        "demonstracao": "https://example.com",
        "autor_publico": "Autor de teste",
        "confirmar": "sim",
    }
    id_criado = None
    try:
        resposta = ana.post("/versoes/importar", data=dados, follow_redirects=False)
        assert resposta.status_code == 303
        id_criado = int(resposta.headers["location"].rsplit("/", 1)[1])
        assert "Melhoria registrada" in ana.get(resposta.headers["location"]).text
        # A ficha publicada e compartilhada; cadastros e dados internos nao sao.
        publico = carla.get(resposta.headers["location"])
        assert publico.status_code == 200 and "Autor de teste" in publico.text
        assert dados["nome"] in carla.get("/versoes?q=z91").text
        assert dados["nome"] not in carla.get("/versoes?q=ausente-z91").text
        assert dados["nome"] not in carla.get("/versoes?categoria=automacao").text
        assert dados["nome"] in ana.get("/versoes?minhas=true").text
        assert dados["nome"] not in carla.get("/versoes?minhas=true").text
        assert ana.get("/versoes/9999999").status_code == 404
        for url in (
            "javascript:alert(1)",
            "https://localhost/x",
            "https://user:senha@example.com",
            "http://example.com",
            "https://127.0.0.1/x",
        ):
            assert ana.post("/versoes/importar", data={**dados, "repositorio": url}).status_code == 400
        assert ana.post("/versoes/importar", data={**dados, "confirmar": ""}).status_code == 400
        assert (
            ana.post(
                "/versoes/importar", data=dados, headers={"origin": "https://outro.example"}
            ).status_code
            == 403
        )
        # Conteudo e texto, nao HTML executavel.
        assert ana.post("/versoes/importar", data={**dados, "nome": "x" * 101}).status_code == 400
    finally:
        if id_criado is not None:
            with SessionLocal() as db:
                db.execute(delete(VersaoComunidade).where(VersaoComunidade.id == id_criado))
                db.commit()
