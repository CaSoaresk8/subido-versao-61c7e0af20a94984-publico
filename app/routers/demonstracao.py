import hashlib
import os
import secrets
import sqlite3

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import DATA_DIR
from app.database import SessionLocal
from app.deps import abrir_sessao
from app.models import Cla, Membro, Missao, Usuario
from app.security import hash_senha

router = APIRouter()


@router.post("/demonstracao/entrar")
def entrar(request: Request, codigo: str = Form(...)):
    chave = os.environ.get("DEMO_CHAVE", "")
    if os.environ.get("DEMO_MODO") != "1" or len(chave) < 32:
        raise HTTPException(404)
    try:
        dados = URLSafeTimedSerializer(chave, salt="subido-demo").loads(codigo, max_age=60)
        if (
            not isinstance(dados, dict)
            or dados.get("aud") != os.environ.get("DEMO_AUDIENCIA")
            or not isinstance(dados.get("nonce"), str)
            or len(dados["nonce"]) != 64
        ):
            raise BadSignature("Código inválido")
    except (BadSignature, SignatureExpired, TypeError):
        raise HTTPException(
            403, "O acesso à demonstração expirou. Abra novamente pela biblioteca."
        ) from None
    fingerprint = hashlib.sha256(dados["nonce"].encode()).hexdigest()
    with sqlite3.connect(DATA_DIR / "demo-usos.db") as controles:
        controles.execute("create table if not exists uso (nonce text primary key)")
        try:
            controles.execute("insert into uso (nonce) values (?)", (fingerprint,))
        except sqlite3.IntegrityError:
            raise HTTPException(
                403, "Este acesso já foi usado. Abra novamente pela biblioteca."
            ) from None
    with SessionLocal() as db:
        visitante = Usuario(
            nome="Visitante",
            email="demo-" + fingerprint + "@exemplo.invalid",
            senha_hash=hash_senha(secrets.token_urlsafe(32)),
        )
        db.add(visitante)
        db.flush()
        cla = Cla(nome="Demonstração", criado_por_id=visitante.id)
        db.add(cla)
        db.flush()
        membro = Membro(cla_id=cla.id, usuario_id=visitante.id, nome="Visitante")
        db.add(membro)
        db.flush()
        db.add(
            Missao(
                cla_id=cla.id,
                titulo="Experimente sua primeira missão",
                descricao="Dados fictícios para conhecer esta versão.",
                pontos=10,
                criada_por_id=membro.id,
            )
        )
        db.commit()
        abrir_sessao(request, membro)
    return RedirectResponse("/", status_code=303)
