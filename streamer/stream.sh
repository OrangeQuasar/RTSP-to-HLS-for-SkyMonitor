#!/bin/sh
set -u

: "${RTSP_URL:?RTSP_URL is required (set it in .env)}"

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
    rm -f /hls/stream.m3u8 /hls/*.ts

    echo "[streamer] starting ffmpeg (codec=${VIDEO_CODEC})"
    # shellcheck disable=SC2086
    ffmpeg -hide_banner -loglevel warning \
        -rtsp_transport tcp \
        -i "$RTSP_URL" \
        $VOPTS \
        -an \
        -f hls \
        -hls_time 1 \
        -hls_list_size 6 \
        -hls_flags delete_segments+independent_segments \
        /hls/stream.m3u8

    echo "[streamer] ffmpeg exited. retrying in 5s..."
    sleep 5
done
