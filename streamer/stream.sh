#!/bin/sh
set -u

: "${RTSP_URL:?RTSP_URL is required (set it in .env)}"

# 複数カメラを同じ /hls, /recordings ボリュームに同居させるためのサブディレクトリ名
CAMERA_NAME="${CAMERA_NAME:-cam}"
HLS_DIR="/hls/${CAMERA_NAME}"
REC_DIR="/recordings/${CAMERA_NAME}"
mkdir -p "$HLS_DIR" "$REC_DIR"

# copy: 無変換で低負荷・低遅延（カメラが H.264 の場合はこれで OK）
# h264: カメラが H.265 などブラウザで再生できないコーデックの場合に再エンコード
VIDEO_CODEC="${VIDEO_CODEC:-copy}"

# 常時録画のファイル分割間隔（秒）。この単位でファイルが切り替わる
RECORDING_SEGMENT_SECONDS="${RECORDING_SEGMENT_SECONDS:-600}"

# 「今すぐ保存」でダウンロードできるクリップの長さ（秒）。api の SAVE_CLIP_SECONDS と揃える
SAVE_CLIP_SECONDS="${SAVE_CLIP_SECONDS:-30}"
# ライブ配信側でその秒数分を切り出せるよう、余裕を持たせてHLSセグメントを保持しておく
HLS_LIST_SIZE=$((SAVE_CLIP_SECONDS + 30))

if [ "$VIDEO_CODEC" = "copy" ]; then
    VOPTS="-c:v copy"
else
    VOPTS="-c:v libx264 -preset veryfast -tune zerolatency -g 30 -b:v 2M"
fi

while true; do
    # 前回のセグメントが残っているとプレイリストが壊れるので消す（録画ファイルは消さない）
    rm -f "$HLS_DIR"/stream.m3u8 "$HLS_DIR"/*.ts

    echo "[streamer:${CAMERA_NAME}] starting ffmpeg (codec=${VIDEO_CODEC})"
    # 同じ RTSP 入力から HLS 配信用と常時録画用の2つの出力を同時に書き出す
    # shellcheck disable=SC2086
    ffmpeg -hide_banner -loglevel warning \
        -rtsp_transport tcp \
        -i "$RTSP_URL" \
        $VOPTS \
        -an \
        -f hls \
        -hls_time 1 \
        -hls_list_size "$HLS_LIST_SIZE" \
        -hls_flags delete_segments+independent_segments \
        "$HLS_DIR/stream.m3u8" \
        $VOPTS \
        -an \
        -f segment \
        -strftime 1 \
        -segment_time "$RECORDING_SEGMENT_SECONDS" \
        -segment_format mp4 \
        -reset_timestamps 1 \
        "$REC_DIR/%Y%m%d_%H%M%S.mp4"

    echo "[streamer:${CAMERA_NAME}] ffmpeg exited. retrying in 5s..."
    sleep 5
done
