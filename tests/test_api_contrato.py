"""O contrato da API, conferido na tabela de rotas em vez de rota por rota.

Duas coisas sao provadas aqui, e as duas sao do tipo que se perde por esquecimento e nao por erro
de raciocinio:

1. Toda rota que ESCREVE exige o cabecalho `X-Requested-With`. Um formulario em outro site consegue
   mandar POST para ca com o cookie da pessoa junto, mas nao consegue mandar cabecalho nenhum. A
   prova e o cabecalho existir, e por isso nenhum valor e conferido em lugar nenhum.

2. Quem nao esta logado recebe 401 em JSON, e nao o 303 da tela. Redirecionar um `fetch` para a
   pagina de login faz o React receber 200 com HTML dentro e achar que deu certo.

A varredura percorre `app.routes` porque a alternativa e escrever um teste por rota, e um teste por
rota nao cobre a rota que alguem adicionar amanha. O que falha aqui e a rota nova que nasceu sem o
`Depends`, sem ninguem ter que lembrar de vir aqui completar a lista.
"""

import re

from fastapi.routing import APIRoute

from app.api.deps import exige_origem_propria

ESCREVEM = {"POST", "PUT", "PATCH", "DELETE"}

CABECALHO = {"X-Requested-With": "teste"}


def coletar(router, prefixo: str = "") -> list[tuple[str, APIRoute]]:
    """Todas as APIRoute da arvore, com o caminho completo de cada uma.

    A recursao e necessaria desde o FastAPI 0.141: `app.include_router` nao copia mais as rotas para
    `app.routes`, ele guarda um `_IncludedRouter` que resolve o roteamento na hora do pedido. Quem
    olhar so `app.routes` procurando APIRoute acha duas (o manifesto e o service worker) e conclui
    que o app nao tem API. O `test_a_varredura_confere_com_o_openapi` existe justamente para essa
    conclusao nao passar despercebida se a estrutura mudar de novo.

    O prefixo do proprio router ja vem embutido em `rota.path`, porque `APIRouter.include_router`
    continua sendo ansioso; o que falta somar e so o prefixo passado no include.
    """
    achados: list[tuple[str, APIRoute]] = []
    for rota in router.routes:
        if isinstance(rota, APIRoute):
            achados.append((prefixo + rota.path, rota))
        elif hasattr(rota, "original_router"):
            achados += coletar(rota.original_router, prefixo + rota.include_context.prefix)
    return achados


def rotas_da_api(app_web) -> list[tuple[str, APIRoute]]:
    return [(caminho, r) for caminho, r in coletar(app_web.router) if caminho.startswith("/api/v1")]


def rotas_que_escrevem(app_web) -> list[tuple[str, APIRoute]]:
    return [(caminho, r) for caminho, r in rotas_da_api(app_web) if r.methods & ESCREVEM]


def pede_o_cabecalho(rota: APIRoute) -> bool:
    """Procura `exige_origem_propria` na arvore de dependencias da rota, em qualquer profundidade.

    `dependencies=[Depends(...)]` no router e na rota caem os dois em `rota.dependant.dependencies`,
    e uma dependencia pode trazer outras dentro. Olhar so o primeiro nivel daria falso negativo no
    dia em que alguem agrupar a exigencia dentro de outra dependencia.
    """
    pilha = list(rota.dependant.dependencies)
    while pilha:
        dependencia = pilha.pop()
        if dependencia.call is exige_origem_propria:
            return True
        pilha.extend(dependencia.dependencies)
    return False


def test_a_varredura_confere_com_o_openapi(app_web):
    """Antes de confiar na varredura, conferir que ela leu o app inteiro.

    Uma lista vazia passaria em todos os testes abaixo sem provar nada: "nenhuma rota esqueceu o
    cabecalho" e verdade trivial quando nenhuma rota foi encontrada. A comparacao e com o
    `openapi()`, que o proprio FastAPI monta pelo caminho dele: se os dois discordam, e a minha
    varredura que esta errada, e nao o app.
    """
    achados = sorted({caminho for caminho, _ in rotas_da_api(app_web)})
    documentados = sorted(p for p in app_web.openapi()["paths"] if p.startswith("/api/v1"))
    assert achados == documentados
    assert len(rotas_que_escrevem(app_web)) > 10


def test_toda_rota_que_escreve_exige_o_cabecalho_de_origem(app_web):
    faltando = [
        f"{sorted(r.methods & ESCREVEM)} {caminho}"
        for caminho, r in rotas_que_escrevem(app_web)
        if not pede_o_cabecalho(r)
    ]
    assert not faltando, "rotas que escrevem sem exigir X-Requested-With: " + ", ".join(faltando)


def test_rota_de_leitura_nao_exige_o_cabecalho(app_web):
    """O outro lado da regra: GET nao pode pedir o cabecalho.

    Exigir em leitura quebraria o `<img src>` do logo e qualquer link aberto em aba nova, e nao
    protegeria nada: o ataque que o cabecalho impede e o de escrita disfarcada de formulario.
    """
    so_leem = [
        caminho
        for caminho, r in rotas_da_api(app_web)
        if not r.methods & ESCREVEM and pede_o_cabecalho(r)
    ]
    assert not so_leem, so_leem


def test_pedido_sem_o_cabecalho_e_recusado_e_nao_escreve(app_web, ana):  # noqa: ARG001
    """A prova viva: a mesma pessoa, logada, sem o cabecalho, nao consegue criar missao.

    403 e nao 401 de proposito: a sessao esta boa, quem foi recusado foi o pedido. Devolver 401 aqui
    mandaria a tela pedir login de novo para quem ja esta dentro.

    A contagem antes e depois esta aqui porque status code nao prova ausencia de escrita: uma rota
    que gravasse e so entao recusasse responderia 403 do mesmo jeito.
    """
    from fastapi.testclient import TestClient

    cliente = TestClient(app_web)
    # O cabecalho vai so no login, para a sessao existir. Dali em diante o cliente nao manda nada.
    entrada = cliente.post(
        "/api/v1/sessao",
        json={"email": "ana@cla.com", "senha": "senhaforte1"},
        headers=CABECALHO,
    )
    assert entrada.status_code == 200, entrada.text

    antes = len(cliente.get("/api/v1/missoes").json()["missoes"])
    recusa = cliente.post("/api/v1/missoes", json={"titulo": "Missao de fora", "pontos": 10})
    assert recusa.status_code == 403, recusa.text
    assert "X-Requested-With" in recusa.json()["detail"]
    assert len(cliente.get("/api/v1/missoes").json()["missoes"]) == antes


def test_com_o_cabecalho_a_mesma_pessoa_escreve(ana_api):
    """O contrapeso do teste acima: o 403 e do cabecalho, nao de estar tudo bloqueado.

    A escrita escolhida e tirar o logo de um cla que nao tem logo. E a unica rota de escrita do app
    que nao muda nada quando repetida, e por isso e a unica que pode ser exercitada dentro do cla da
    Ana sem mexer nas contagens de que os outros testes dependem.
    """
    resposta = ana_api.delete("/api/v1/clas/atual/logo")
    assert resposta.status_code == 200, resposta.text
    # Sem logo, o simbolo volta a ser o icone do app, e ele sai versionado: e o mesmo endereco que o
    # HTML usa, e o `?v=` e o que faz o cliente buscar a arte nova em vez da que ja tem guardada.
    simbolo = resposta.json()["simbolo"]
    assert re.fullmatch(r"/static/icone-192\.png\?v=\d+", simbolo), simbolo


def test_sair_funciona_sem_sessao_mas_nao_sem_cabecalho(app_web):
    """Sair e a unica escrita que nao exige estar logado. O cabecalho ela exige do mesmo jeito.

    Pedir login para quem quer sair seria absurdo: a tela manda este pedido exatamente quando
    desconfia que a sessao morreu. Ja o cabecalho continua valendo, porque "deslogar de longe" e
    uma coisa que outro site nao pode fazer com o cookie da pessoa.
    """
    from fastapi.testclient import TestClient

    cliente = TestClient(app_web)
    assert cliente.delete("/api/v1/sessao").status_code == 403
    assert cliente.delete("/api/v1/sessao", headers=CABECALHO).status_code == 204


def test_sem_sessao_a_api_responde_401_em_json(visitante):
    """A diferenca que separa a API da tela: aqui nao se redireciona para /login.

    `follow_redirects=False` nao e enfeite: com redirect ligado, um 303 para /login viraria 200 com
    HTML, e a assercao passaria achando que a rota respondeu.
    """
    resposta = visitante.get("/api/v1/painel", follow_redirects=False)
    assert resposta.status_code == 401
    assert resposta.headers["content-type"].startswith("application/json")
    assert "login" in resposta.json()["detail"].lower()


def test_saude_responde_sem_sessao_e_sem_cabecalho(visitante):
    """A rota do health check da Fly. Sem sessao e sem banco, que e o que ela precisa provar."""
    resposta = visitante.get("/api/v1/saude")
    assert resposta.status_code == 200
    assert resposta.json() == {"ok": True}
