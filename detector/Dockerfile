FROM python:3.11-slim

# atomcam.py の実行に必要なシステム依存
# - ffmpeg: OpenCV の RTSP デコードに使う実体バイナリ
# - libgl1 / libglib2.0-0: opencv-python-headless でも一部ビルドで要求される
# - tzdata: -t（終了時刻）判定を日本時間で行うため
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ffmpeg libgl1 libglib2.0-0 tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Tokyo

RUN pip install --no-cache-dir opencv-python-headless numpy imutils

RUN git clone --depth 1 https://github.com/kin-hasegawa/meteor-detect.git /app
WORKDIR /app

ENTRYPOINT ["python", "atomcam.py"]
