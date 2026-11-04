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
# ライブ配信側でその秒数分を切り出せるよう、余裕を持たせてHLSセグメントを保持しておく（1セグメント≒1秒）
HLS_LIST_SIZE=$((SAVE_CLIP_SECONDS + 30))

# 夜間のみ録画（アーカイブ）する設定。ライブ配信は時間帯に関わらず常時継続する
RECORDING_NIGHT_ONLY="${RECORDING_NIGHT_ONLY:-false}"
RECORDING_START_HOUR="${RECORDING_START_HOUR:-18}" # 録画開始時刻（0-23時）
RECORDING_END_HOUR="${RECORDING_END_HOUR:-6}"       # 録画終了時刻（0-23時、開始より小さければ日をまたぐ）
# 開始・終了時刻を判定するタイムゾーン（POSIX 形式。tzdata 不要）。録画ファイル名は従来どおり UTC
RECORDING_HOURS_TZ="${RECORDING_HOURS_TZ:-JST-9}"

# 監視ループの間隔と、HLS 側 ffmpeg が落ちたときの再起動待ち時間（秒）
WATCH_INTERVAL_SECONDS=10
HLS_RESTART_DELAY_SECONDS=5

HLS_PID=""
REC_PID=""

log() {
    echo "[streamer:${CAMERA_NAME}] $*"
}

is_running() {
    [ -n "$1" ] && kill -0 "$1" 2>/dev/null
}

stop_process() {
    if is_running "$1"; then
        kill -TERM "$1" 2>/dev/null
        wait "$1" 2>/dev/null
    fi
}

# RTSP を受信して映像のみを出力する ffmpeg を起動する（出力先の指定は引数で渡す）
# HLS 用・録画用で入力とコーデックの指定を共通化している
run_ffmpeg() {
    if [ "$VIDEO_CODEC" = "copy" ]; then
        set -- -c:v copy "$@"
    else
        set -- -c:v libx264 -preset veryfast -tune zerolatency -g 30 -b:v 2M "$@"
    fi
    ffmpeg -hide_banner -loglevel warning \
        -rtsp_transport tcp \
        -i "$RTSP_URL" \
        -an \
        "$@" &
}

# 現在時刻が録画対象の時間帯かどうか判定する
should_record_now() {
    [ "$RECORDING_NIGHT_ONLY" = "true" ] || return 0

    hour=$(TZ="$RECORDING_HOURS_TZ" date +%H)
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
    log "starting HLS ffmpeg (codec=${VIDEO_CODEC})"
    rm -f "$HLS_DIR"/stream.m3u8 "$HLS_DIR"/*.ts
    run_ffmpeg \
        -f hls \
        -hls_time 1 \
        -hls_list_size "$HLS_LIST_SIZE" \
        -hls_flags delete_segments+independent_segments \
        "$HLS_DIR/stream.m3u8"
    HLS_PID=$!
}

start_recording() {
    log "starting recording ffmpeg"
    run_ffmpeg \
        -f segment \
        -strftime 1 \
        -segment_time "$RECORDING_SEGMENT_SECONDS" \
        -segment_format mp4 \
        -reset_timestamps 1 \
        "$REC_DIR/%Y%m%d_%H%M%S.mp4"
    REC_PID=$!
}

stop_recording() {
    if is_running "$REC_PID"; then
        log "stopping recording ffmpeg (outside recording hours)"
        stop_process "$REC_PID"
    fi
    REC_PID=""
}

shutdown() {
    stop_recording
    stop_process "$HLS_PID"
    exit 0
}
trap shutdown INT TERM

start_hls

while true; do
    if ! is_running "$HLS_PID"; then
        log "HLS ffmpeg exited. restarting in ${HLS_RESTART_DELAY_SECONDS}s..."
        sleep "$HLS_RESTART_DELAY_SECONDS"
        start_hls
    fi

    if should_record_now; then
        if ! is_running "$REC_PID"; then
            [ -n "$REC_PID" ] && log "recording ffmpeg exited. restarting..."
            start_recording
        fi
    else
        stop_recording
    fi

    sleep "$WATCH_INTERVAL_SECONDS"
done
