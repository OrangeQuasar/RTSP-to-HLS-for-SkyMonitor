FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# 「今すぐ保存」でHLSセグメントをmp4に結合するために使う
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 依存だけ先に解決してレイヤーキャッシュを効かせる
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY main.py ./

EXPOSE 8000

CMD ["uv", "run", "--frozen", "uvicorn", "main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
