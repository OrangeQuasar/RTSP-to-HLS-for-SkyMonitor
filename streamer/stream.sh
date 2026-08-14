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

# 夜間のみ録画（アーカイブ）する設定。ライブ配信は時間帯に関わらず常時継続する
RECORDING_NIGHT_ONLY="${RECORDING_NIGHT_ONLY:-false}"
RECORDING_START_HOUR="${RECORDING_START_HOUR:-18}" # 録画開始時刻（0-23時）
RECORDING_END_HOUR="${RECORDING_END_HOUR:-6}"       # 録画終了時刻（0-23時、開始より小さければ日をまたぐ）

if [ "$VIDEO_CODEC" = "copy" ]; then
    VOPTS="-c:v copy"
else
    VOPTS="-c:v libx264 -preset veryfast -tune zerolatency -g 30 -b:v 2M"
fi

HLS_PID=""
REC_PID=""

# 現在時刻が録画対象の時間帯かどうか判定する
should_record_now() {
    if [ "$RECORDING_NIGHT_ONLY" != "true" ]; then
        return 0
    fi
    hour=$(date +%H)
    hour=${hour#0} # 先頭ゼロを外す（"08"などが不正な8進数と解釈されるのを防ぐ）
    hour=${hour:-0}
    if [ "$RECORDING_START_HOUR" -le "$RECORDING_END_HOUR" ]; then
        [ "$hour" -ge "$RECORDING_START_HOUR" ] && [ "$hour" -lt "$RECORDING_END_HOUR" ]
    else
        # 例: 18時開始・6時終了のように日をまたぐ場合
        [ "$hour" -ge "$RECORDING_START_HOUR" ] || [ "$hour" -lt "$RECORDING_END_HOUR" ]
    fi
}

start_hls() {
    echo "[streamer:${CAMERA_NAME}] starting HLS ffmpeg (codec=${VIDEO_CODEC})"
    rm -f "$HLS_DIR"/stream.m3u8 "$HLS_DIR"/*.ts
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
        "$HLS_DIR/stream.m3u8" &
    HLS_PID=$!
}

start_recording() {
    echo "[streamer:${CAMERA_NAME}] starting recording ffmpeg"
    # shellcheck disable=SC2086
    ffmpeg -hide_banner -loglevel warning \
        -rtsp_transport tcp \
        -i "$RTSP_URL" \
        $VOPTS \
        -an \
        -f segment \
        -strftime 1 \
        -segment_time "$RECORDING_SEGMENT_SECONDS" \
        -segment_format mp4 \
        -reset_timestamps 1 \
        "$REC_DIR/%Y%m%d_%H%M%S.mp4" &
    REC_PID=$!
}

stop_recording() {
    if [ -n "$REC_PID" ] && kill -0 "$REC_PID" 2>/dev/null; then
        echo "[streamer:${CAMERA_NAME}] stopping recording ffmpeg (outside recording hours)"
        kill -TERM "$REC_PID" 2>/dev/null
        wait "$REC_PID" 2>/dev/null
    fi
    REC_PID=""
}

cleanup() {
    stop_recording
    if [ -n "$HLS_PID" ] && kill -0 "$HLS_PID" 2>/dev/null; then
        kill -TERM "$HLS_PID" 2>/dev/null
        wait "$HLS_PID" 2>/dev/null
    fi
    exit 0
}
trap cleanup INT TERM

start_hls

while true; do
    if ! kill -0 "$HLS_PID" 2>/dev/null; then
        echo "[streamer:${CAMERA_NAME}] HLS ffmpeg exited. restarting in 5s..."
        sleep 5
        start_hls
    fi

    if should_record_now; then
        if [ -z "$REC_PID" ] || ! kill -0 "$REC_PID" 2>/dev/null; then
            [ -n "$REC_PID" ] && echo "[streamer:${CAMERA_NAME}] recording ffmpeg exited. restarting..."
            start_recording
        fi
    else
        stop_recording
    fi

    sleep 10
done
