def test_aulas_exigem_login(visitante):
    resposta = visitante.get("/aulas-ia", follow_redirects=False)
    assert resposta.status_code == 303
    assert "/login" in resposta.headers["location"]


def test_aulas_no_menu_e_videos_corretos(ana):
    resposta = ana.get("/aulas-ia")
    assert resposta.status_code == 200
    assert 'href="/aulas-ia" class="ativo"' in resposta.text
    for video in ("cMISpVp0a64", "8wL4UFu3EHo"):
        assert f'data-aula="{video}"' in resposta.text

    assert ana.get("/static/aulas-ia.js").status_code == 200
    assert "Abrir no YouTube" not in resposta.text
    for numero in (1, 2):
        assert ana.get(f"/static/aula-ia-{numero}-v2.webp").status_code == 200


def test_ordem_e_texto_das_capas(ana):
    from app.routers.aulas_ia import AULAS

    assert AULAS[0]["id"] == "8wL4UFu3EHo"
    assert AULAS[0]["capa"] == "aula-ia-2-v2.webp"
    assert AULAS[1]["id"] == "cMISpVp0a64"
    assert AULAS[1]["capa"] == "aula-mcp-meta-v3.webp"
    assert ana.get("/static/aula-mcp-meta-v3.webp").status_code == 200
    html = ana.get("/aulas-ia").text
    assert html.index('data-aula="8wL4UFu3EHo"') < html.index('data-aula="cMISpVp0a64"')
    assert "Otimização de campanha com MCP do Meta" in html
