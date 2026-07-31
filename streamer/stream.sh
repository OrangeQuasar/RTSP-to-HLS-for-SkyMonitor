#!/bin/sh
set -u

: "${RTSP_URL:?RTSP_URL is required (set it in .env)}"

# 複数カメラを同じ /hls ボリュームに同居させるためのサブディレクトリ名
CAMERA_NAME="${CAMERA_NAME:-cam}"
HLS_DIR="/hls/${CAMERA_NAME}"
mkdir -p "$HLS_DIR"

# copy: 無変換で低負荷・低遅延（カメラが H.264 の場合はこれで OK）
# h264: カメラが H.265 などブラウザで再生できないコーデックの場合に再エンコード
VIDEO_CODEC="${VIDEO_CODEC:-copy}"

if [ "$VIDEO_CODEC" = "copy" ]; then
    VOPTS="-c:v copy"
else
    VOPTS="-c:v libx264 -preset veryfast -tune zerolatency -g 30 -b:v 2M"
fi

while true; do
    # 前回のセグメントが残っているとプレイリストが壊れるので消す
    rm -f "$HLS_DIR"/stream.m3u8 "$HLS_DIR"/*.ts

    echo "[streamer:${CAMERA_NAME}] starting ffmpeg (codec=${VIDEO_CODEC})"
    # shellcheck disable=SC2086
    ffmpeg -hide_banner -loglevel warning \
        -rtsp_transport tcp \
        -i "$RTSP_URL" \
        $VOPTS \
        -an \
        -f hls \
        -hls_time 1 \
        -hls_list_size 15 \
        -hls_flags delete_segments+independent_segments \
        "$HLS_DIR/stream.m3u8"

    echo "[streamer:${CAMERA_NAME}] ffmpeg exited. retrying in 5s..."
    sleep 5
done
