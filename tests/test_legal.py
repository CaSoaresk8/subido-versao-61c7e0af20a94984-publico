"""Privacidade e termos: publicas, achaveis e dizendo o que o app faz com os dados do Google.

Nao e teste de texto bonito. Sao tres coisas que, se quebrarem, quebram em silencio e so aparecem
quando o Google recusa a publicacao do app (e ai os convites param de sair em todos os clas):
as paginas abrirem SEM login, estarem linkadas nas telas de entrada, e a politica descrever o uso
do escopo que o app de fato pede.
"""

from __future__ import annotations

PAGINAS = ("/privacidade", "/termos")


def test_abrem_sem_login(visitante):
    """O Google abre esses endereços deslogado. Um 303 para /login reprova a publicacao."""
    for url in PAGINAS:
        resposta = visitante.get(url, follow_redirects=False)
        assert resposta.status_code == 200, f"{url} respondeu {resposta.status_code} para visitante"


def test_estao_no_pe_das_telas_de_entrada(visitante):
    for url in ("/login", "/criar-cla", "/tutorial"):
        texto = visitante.get(url).text
        assert 'href="/privacidade"' in texto, f"{url} nao aponta para a privacidade"
        assert 'href="/termos"' in texto, f"{url} nao aponta para os termos"


def test_a_politica_descreve_o_uso_dos_dados_do_google(visitante):
    """O escopo citado tem que ser o mesmo que o app pede, e a pagina tem que citar o Uso Limitado.

    Se um dia o app pedir um escopo mais largo (a agenda inteira, por exemplo) e ninguem lembrar de
    mudar esta pagina, este teste quebra: ele le o escopo de `google_agenda.ESCOPOS`, e nao uma
    copia escrita aqui.
    """
    from app.servicos.google_agenda import ESCOPOS

    texto = visitante.get("/privacidade").text
    pedidos = [e.rsplit("/", 1)[1] for e in ESCOPOS.split() if e.startswith("http")]
    for escopo in pedidos:
        assert escopo in texto, f"a politica nao fala do escopo {escopo} que o app pede"
    assert "api-services-user-data-policy" in texto, "falta o link da politica de dados do Google"
    assert "Uso Limitado" in texto
    # A promessa mais forte da pagina: o app so mexe nos eventos que ele mesmo criou.
    assert "somente os" in texto and "eventos que ele próprio criou" in texto


def test_o_usuario_logado_continua_com_o_menu(ana):
    """Sem `membro_opcional` a pagina abriria igual, mas quem esta logado cairia numa tela sem menu."""
    texto = ana.get("/privacidade").text
    assert 'href="/agenda"' in texto and 'href="/historico"' in texto
