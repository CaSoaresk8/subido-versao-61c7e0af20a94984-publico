"""O quadro pessoal: a pagina /minhas e o arrastar de cartao.

O `POST /minhas/mover` responde JSON desde antes de existir API, e o contrato dele (`{"ok": true,
"pontos": n}` ou 409 com `{mensagem, url}`) e o que `app/static/kanban.js` ja espera hoje. Ele fica
como esta: quem inventa um contrato novo aqui quebra o arrastar que funciona.
"""

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.deps import escopo_logado, templates
from app.escopo import EscopoCla
from app.repositorios import colunas as repo_colunas
from app.repositorios import missoes as repo_missoes
from app.servicos.calendario import MESES, eventos_do_cla, grade_do_mes
from app.servicos.colunas import MAX_COLUNAS
from app.servicos.missoes import frase_de_falta_de_resposta
from app.servicos.quadro import (
    VISOES,
    colocar,
    montar_itens,
    montar_quadro,
    mover as mover_cartoes,
    pontos,
    resolver_destino,
)


def recusa_por_falta_de_resposta(missao) -> dict:
    """A frase e a URL que o kanban mostra quando a missao barra o movimento.

    Fica aqui e nao no servico porque `/missoes/{id}?erro=resposta` e endereco de tela: o servico
    devolve a missao que barrou, e cada interface diz para onde ir com isso.
    """
    return {
        "ok": False,
        "mensagem": frase_de_falta_de_resposta(missao),
        "url": f"/missoes/{missao.id}?erro=resposta",
    }


router = APIRouter(prefix="/minhas")


def _minha_mentoria(escopo) -> dict | None:
    """O bloco de mentoria da propria pessoa: saldo e proximas consultorias.

    So aparece para quem a mentoria acompanha (tem registro de acompanhamento ou alguma consultoria
    marcada). Para os outros, e um bloco que nao existe, e nao um bloco vazio dizendo "0 de 12".
    A anotacao do rastreador nao vai: ela e dele.
    """
    from app.models import CONSOME_SALDO
    from app.repositorios import rastreadores as repo_rastreadores
    from app.servicos import mentoria as servico_mentoria
    from app.servicos.agenda import agora_local

    pessoa = escopo.membro
    mentorias = repo_rastreadores.mentorias_da_pessoa(escopo.db, pessoa)
    if not mentorias and repo_rastreadores.acompanhamento_da_pessoa(escopo.db, pessoa) is None:
        return None
    agora = agora_local()
    return {
        "saldo": servico_mentoria.saldo(escopo.db, pessoa),
        "proximas": sorted(
            (m for m in mentorias if m.inicio >= agora and m.situacao in CONSOME_SALDO),
            key=lambda m: m.inicio,
        ),
    }


@router.get("")
def minhas(
    request: Request,
    visao: str = "kanban",
    ano: int | None = None,
    mes: int | None = None,
    erro: str | None = None,
    escopo: EscopoCla = Depends(escopo_logado),
):
    membro = escopo.membro
    if visao not in VISOES:
        visao = "kanban"
    hoje = date.today()
    ano = ano or hoje.year
    mes = mes if mes and 1 <= mes <= 12 else hoje.month

    colunas = repo_colunas.do_membro(escopo, membro.id)
    missoes = repo_missoes.ativas(escopo)
    itens = montar_itens(escopo, {c.id for c in colunas}, missoes)
    grupos = montar_quadro(itens, colunas, membro.ordem_quadro)
    coluna_do_item = {i["chave"]: g["chave"] for g in grupos for i in g["itens"]}

    return templates.TemplateResponse(
        request,
        "minhas.html",
        {
            "membro": membro,
            "visao": visao,
            "itens": itens,
            "grupos": grupos,
            "coluna_do_item": coluna_do_item,
            "pode_criar_coluna": len(colunas) < MAX_COLUNAS,
            "mentoria": _minha_mentoria(escopo),
            "erro_saldo": request.query_params.get("erro_saldo"),
            "erro": erro,
            "semanas": grade_do_mes(ano, mes, eventos_do_cla(escopo, missoes, membro.id, ano, mes)),
            "mes_nome": MESES[mes - 1],
            "ano": ano,
            "mes": mes,
            "mes_anterior": (ano - 1, 12) if mes == 1 else (ano, mes - 1),
            "mes_seguinte": (ano + 1, 1) if mes == 12 else (ano, mes + 1),
            "pontos_meus": pontos(itens),
        },
    )


@router.post("/mover")
async def mover(request: Request, escopo: EscopoCla = Depends(escopo_logado)):
    dados = await request.json()
    chaves = dados.get("itens") or []
    if not isinstance(chaves, list):
        raise HTTPException(status_code=400, detail="Lista de itens inválida")

    barrou = mover_cartoes(escopo, str(dados.get("destino", "")), chaves)
    if barrou is not None:
        return JSONResponse(recusa_por_falta_de_resposta(barrou), status_code=409)
    escopo.db.commit()

    colunas = repo_colunas.do_membro(escopo, escopo.membro_id)
    itens = montar_itens(escopo, {c.id for c in colunas}, repo_missoes.ativas(escopo))
    return JSONResponse({"ok": True, "pontos": pontos(itens)})


@router.post("/mover-form")
def mover_form(
    chave: str = Form(...),
    destino: str = Form(...),
    visao: str = Form("kanban"),
    escopo: EscopoCla = Depends(escopo_logado),
):
    coluna_id, status = resolver_destino(escopo, destino)
    barrou = colocar(escopo, chave, coluna_id, status, 9999)
    if barrou is not None:
        escopo.db.rollback()
        return RedirectResponse(f"/missoes/{barrou.id}?erro=resposta", status_code=303)
    escopo.db.commit()
    return RedirectResponse(f"/minhas?visao={visao}", status_code=303)


@router.post("/saldo")
def ajustar_meu_saldo(
    mensais: int = Form(...),
    livres: int = Form(...),
    escopo: EscopoCla = Depends(escopo_logado),
):
    """A pessoa ajusta o total das proprias consultorias. Decisao do Caio; o registro leva o nome."""
    from urllib.parse import quote

    from app.servicos import mentoria as servico_mentoria
    from app.servicos.erros import ForaDeRegra

    try:
        servico_mentoria.ajustar_proprio_saldo(escopo, mensais, livres)
    except ForaDeRegra as recusa:
        escopo.db.rollback()
        return RedirectResponse(f"/minhas?erro_saldo={quote(str(recusa))}", status_code=303)
    escopo.db.commit()
    return RedirectResponse("/minhas", status_code=303)
