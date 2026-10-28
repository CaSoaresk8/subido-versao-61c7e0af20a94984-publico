"""Cria a primeira missao do cla. Rode depois que pelo menos uma conta existir."""

from datetime import date

from sqlalchemy import select

from app.database import SessionLocal
from app.esquema import atualizar as atualizar_esquema
from app.models import Membro, Missao
from app.servicos.auditoria import registrar

TITULO = "Resumo do Curso Subido de Trafego"

atualizar_esquema()

with SessionLocal() as db:
    autor = db.scalar(select(Membro).order_by(Membro.id))
    if autor is None:
        raise SystemExit("Crie uma conta no app antes de rodar o seed.")

    if db.scalar(select(Missao).where(Missao.titulo == TITULO)):
        raise SystemExit(f"A missao '{TITULO}' ja existe.")

    missao = Missao(
        titulo=TITULO,
        descricao=(
            "Assistir ao curso Subido de Trafego e entregar um resumo escrito. "
            "Cole o link do resumo ou escreva o resumo direto no campo da entrega."
        ),
        pontos=500,
        vencimento=date(2026, 9, 30),
        criada_por_id=autor.id,
        exige_resposta=True,
        rotulo_resposta="Link do resumo ou o resumo escrito aqui",
    )
    db.add(missao)
    db.flush()
    registrar(db, autor.id, "criou", "missao", missao.id, TITULO)
    db.commit()
    print(f"Missao criada: {TITULO} (500 pts, vence 30/09/2026)")
