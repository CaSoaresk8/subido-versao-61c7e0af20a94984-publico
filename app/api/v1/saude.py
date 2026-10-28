"""A rota que a Fly.io usa para saber se a maquina esta viva.

Hoje o `fly.toml` bate em `/login`, e isso e uma armadilha combinada: `/login` renderiza template,
toca a sessao e, na fase 6, deixa de existir. Health check apontado para tela de UI transforma
qualquer defeito de front em maquina derrubada e reiniciada em ciclo, que e a pior hora possivel
para perder o servidor: justamente quando alguem precisa entrar nele para ver o que quebrou.

Sem sessao e sem banco de proposito. "O processo esta de pe e respondendo HTTP" e uma pergunta, "o
banco responde" e outra: misturar as duas faz um SQLite travado por escrita concorrente virar
reinicio de maquina, e reiniciar nao destrava lock nenhum.
"""

from fastapi import APIRouter

router = APIRouter(tags=["saude"])


@router.get("/saude")
def saude() -> dict:
    return {"ok": True}
