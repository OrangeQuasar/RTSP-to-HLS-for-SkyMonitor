FROM python:3.11-slim

# atomcam.py の実行に必要なシステム依存
# - ffmpeg: OpenCV の RTSP デコードに使う実体バイナリ
# - xvfb / xauth: -n(no_window)指定時でも cv2.waitKey() が無条件に呼ばれるため、
#   実ディスプレイの代わりに仮想ディスプレイを用意して GUI 呼び出しを成立させる（xvfb-run が xauth に依存）
# - libgl1 / libglib2.0-0 / libsm6 / libxext6 / libxrender1: opencv-python(GUI版)の実行に必要
# - tzdata: -t（終了時刻）判定を日本時間で行うため
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ffmpeg xvfb xauth libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Tokyo

RUN pip install --no-cache-dir opencv-python numpy imutils \
    pafy youtube_dl

RUN git clone --depth 1 https://github.com/kin-hasegawa/meteor-detect.git /app
WORKDIR /app

ENTRYPOINT ["xvfb-run", "-a", "python", "atomcam.py"]
