FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# 依存だけ先に解決してレイヤーキャッシュを効かせる
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY main.py ./

EXPOSE 8000

CMD ["uv", "run", "--frozen", "uvicorn", "main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
