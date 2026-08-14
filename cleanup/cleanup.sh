#!/bin/sh
set -u

RECORDINGS_DIR="/recordings"
RETENTION_DAYS="${RECORDING_RETENTION_DAYS:-3}"
CHECK_INTERVAL_SECONDS="${CLEANUP_INTERVAL_SECONDS:-3600}"

echo "[cleanup] retention=${RETENTION_DAYS}days interval=${CHECK_INTERVAL_SECONDS}s"

while true; do
    deleted=$(find "$RECORDINGS_DIR" -type f -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)
    # 空になったカメラ別ディレクトリを削除
    find "$RECORDINGS_DIR" -mindepth 1 -type d -empty -delete
    echo "[cleanup] removed ${deleted} file(s) older than ${RETENTION_DAYS} days"
    sleep "$CHECK_INTERVAL_SECONDS"
done
