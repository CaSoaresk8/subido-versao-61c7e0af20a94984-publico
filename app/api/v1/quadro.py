"""O quadro pessoal montado, e o arrastar de cartao.

O `POST /minhas/mover` do HTML ja e JSON desde antes de existir API, e o contrato dele (`{"ok":
true, "pontos": n}`, ou 409 com `{"mensagem", "url"}`) e o que `app/static/kanban.js` fala hoje. A
rota daqui responde a MESMA coisa, com o mesmo corpo nos dois casos. Nao e coincidencia nem
preguica: durante as fases 5 e 6 as duas interfaces vao arrastar cartao ao mesmo tempo, e um
contrato so e o que impede que "mover" queira dizer duas coisas diferentes dependendo de quem pediu.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api import saida
from app.api.deps import escopo_api, exige_origem_propria
from app.escopo import EscopoCla
from app.repositorios import colunas as repo_colunas
from app.repositorios import missoes as repo_missoes
from app.servicos import quadro as servico_quadro
from app.servicos.missoes import frase_de_falta_de_resposta

router = APIRouter(tags=["quadro"])


class Movimento(BaseModel):
    """A coluna INTEIRA, na ordem final, e nao o cartao que se moveu.

    Soltar um cartao no meio de uma pilha muda a posicao de todos os que estao abaixo dele. Mandar
    so o que mudou obrigaria os dois lados a concordar sobre como as posicoes se deslocam, e essa e
    uma conta que sai diferente em cada lugar que a refaz.
    """

    destino: str
    itens: list[str] = []


def montar(escopo: EscopoCla) -> dict:
    colunas = repo_colunas.do_membro(escopo, escopo.membro_id)
    missoes = repo_missoes.ativas(escopo)
    itens = servico_quadro.montar_itens(escopo, {c.id for c in colunas}, missoes)
    grupos = servico_quadro.montar_quadro(itens, colunas, escopo.membro.ordem_quadro)
    return {
        "grupos": [saida.grupo_do_quadro(g) for g in grupos],
        "pontos": servico_quadro.pontos(itens),
    }


@router.get("/quadro")
def ver(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """O quadro pronto: os grupos na ordem que a pessoa arrastou, com os cartoes dentro.

    Vem montado do servidor, e nao como tres listas para o React juntar. Quem decide que um cartao
    concluido dentro de coluna privada nao pontua e `servicos/missoes.py:conta_como_concluida`, e
    essa decisao ja desandou em duas versoes uma vez. Uma terceira versao dela em TypeScript e o
    mesmo erro com outro nome.
    """
    return montar(escopo)


@router.post("/quadro/mover", dependencies=[Depends(exige_origem_propria)])
def mover(pedido: Movimento, escopo: EscopoCla = Depends(escopo_api)):
    """Poe a coluna na ordem recebida. 409 quando uma missao exige resposta e ainda nao tem.

    O rollback de um movimento barrado acontece dentro do servico, porque quando o quinto cartao
    barra os quatro anteriores ja foram escritos. Sair sem desfazer gravaria um movimento pela
    metade, e o quadro voltaria diferente do que a tela esta mostrando.
    """
    barrou = servico_quadro.mover(escopo, pedido.destino, pedido.itens)
    if barrou is not None:
        return JSONResponse(
            {
                "ok": False,
                "mensagem": frase_de_falta_de_resposta(barrou),
                "url": f"/missoes/{barrou.id}?erro=resposta",
            },
            status_code=409,
        )
    escopo.db.commit()
    return {"ok": True, "pontos": montar(escopo)["pontos"]}
