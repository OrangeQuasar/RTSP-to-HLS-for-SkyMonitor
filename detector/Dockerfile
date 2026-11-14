# 流星検出（meteor-detect の atomcam.py）を動かすイメージ
# meteor-detect/ は docker-compose.yml の additional_contexts で "meteor-detect" として渡す
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# ffmpeg: 検出動画を H.264 に変換する / libgl1, libglib2.0-0: opencv-python が必要とする
# tzdata: 検出時刻とファイル名を日本時間にする（TZ=Asia/Tokyo）
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    TZ=Asia/Tokyo

# 依存だけ先に解決してレイヤーキャッシュを効かせる
COPY --from=meteor-detect pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY --from=meteor-detect atomcam.py ./
COPY run.py ./

CMD ["/app/.venv/bin/python", "run.py"]
