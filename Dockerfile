FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    DATA_DIR=/data \
    PRODUCAO=1

EXPOSE 8080
# --proxy-headers com --forwarded-allow-ips="*": o app so e alcancavel pelo proxy do Fly, que termina
# o HTTPS e avisa isso no X-Forwarded-Proto. Sem confiar nesse cabecalho, o app se enxergava como
# http://, e o link de convite saia "http://cla.ialabor.com/convite/..." e o retorno do login do
# Google, que exige o endereco https exato cadastrado, nao bateria.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
