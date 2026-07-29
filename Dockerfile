FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# 依存だけ先に解決してレイヤーキャッシュを効かせる
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY main.py ./

EXPOSE 8501

CMD ["uv", "run", "--frozen", "streamlit", "run", "main.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
