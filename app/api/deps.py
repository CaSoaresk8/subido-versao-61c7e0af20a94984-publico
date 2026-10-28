"""Quem esta logado e quem pode escrever, do lado da API.

Duas coisas que a camada de HTML resolve de um jeito que nao serve para JSON.

**Sem sessao, a resposta e 401 e nao um desvio para o login.** `escopo_logado` levanta um 303 com
`Location: /login`, que e o certo para quem esta navegando. Para um `fetch` e o pior dos mundos: o
navegador segue o desvio sozinho, a tela de login volta como 200 com HTML dentro, e o codigo que
esperava JSON quebra a parsear, num lugar que nao tem nada a ver com login. O 401 diz a verdade no
proprio codigo da resposta, e quem chamou decide se manda para o login ou so mostra o aviso.

**Toda rota que escreve exige um header.** O cookie de sessao viaja sozinho em qualquer pedido que
o navegador faca, inclusive num POST que um site de terceiro disparou com um formulario escondido.
`SameSite=lax` ja barra o grosso disso, e o cookie daqui e lax; mas ele e uma defesa do navegador, e
navegador e justamente a parte que nao esta sob o nosso controle. `X-Requested-With` e a segunda
camada, e ela e estrutural: formulario HTML nao consegue mandar header nenhum, e `fetch` de outra
origem so manda header custom depois de um preflight que este app nunca responde. Quem consegue por
o header ja estava na mesma origem.

Nao ha token de CSRF em cookie duplo porque ele nao acrescentaria nada aqui: o SPA vai ser servido
pela mesma origem da API, entao o header sozinho ja separa "veio de dentro" de "veio de fora", e um
segundo cookie so daria mais uma coisa para sincronizar.

`tests/test_api_contrato.py` percorre as rotas registradas e falha se alguma que escreve tiver
esquecido de pedir o header. Depender de lembrar seria depender da pessoa mais distraida do dia.
"""

from fastapi import Depends, Header, HTTPException

from app.deps import escopo_opcional
from app.escopo import EscopoCla

CABECALHO_DE_ORIGEM = "X-Requested-With"


def exige_origem_propria(x_requested_with: str = Header(default="")) -> None:
    """Recusa o pedido que nao tem como ter saido de uma tela deste app.

    Qualquer valor serve, e nao so "XMLHttpRequest": o que prova a origem e o header EXISTIR, nao o
    que esta escrito nele. Exigir um texto exato daria a impressao de que o texto e o segredo, e
    segredo nenhum viaja em header que qualquer script da propria pagina le.

    403 e nao 401 de proposito: 401 quer dizer "faca login", e quem cai aqui pode estar
    perfeitamente logado. O que falta e a prova de que o pedido nasceu aqui dentro.
    """
    if not x_requested_with.strip():
        raise HTTPException(
            status_code=403,
            detail=f"Pedido sem o cabeçalho {CABECALHO_DE_ORIGEM}.",
        )


def escopo_api(escopo: EscopoCla | None = Depends(escopo_opcional)) -> EscopoCla:
    """O escopo de quem esta logado, ou 401. E o `escopo_logado` sem o desvio para o login."""
    if escopo is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    return escopo
