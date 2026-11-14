#!/bin/sh
set -u

RECORDINGS_DIR="/recordings"
RETENTION_DAYS="${RECORDING_RETENTION_DAYS:-3}"
# 流星の検出結果（比較明合成画像・動画）は数が少なく残しておきたいので、録画とは別の期間にする
METEORS_DIR="/meteors"
METEOR_RETENTION_DAYS="${METEOR_RETENTION_DAYS:-30}"
CHECK_INTERVAL_SECONDS="${CLEANUP_INTERVAL_SECONDS:-3600}"

echo "[cleanup] retention=${RETENTION_DAYS}days meteors=${METEOR_RETENTION_DAYS}days interval=${CHECK_INTERVAL_SECONDS}s"

while true; do
    deleted=$(find "$RECORDINGS_DIR" -type f -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)
    echo "[cleanup] removed ${deleted} file(s) older than ${RETENTION_DAYS} days"
    if [ -d "$METEORS_DIR" ]; then
        deleted=$(find "$METEORS_DIR" -type f -mtime "+${METEOR_RETENTION_DAYS}" -print -delete | wc -l)
        echo "[cleanup] removed ${deleted} meteor file(s) older than ${METEOR_RETENTION_DAYS} days"
    fi
    sleep "$CHECK_INTERVAL_SECONDS"
done
