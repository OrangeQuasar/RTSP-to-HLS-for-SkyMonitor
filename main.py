import os
import re
import time
from pathlib import Path

from fastapi import FastAPI

HLS_ROOT = Path(os.environ.get("HLS_ROOT", "/hls"))
RECORDINGS_ROOT = Path(os.environ.get("RECORDINGS_ROOT", "/recordings"))
# プレイリストの更新が止まってからこの秒数を超えたらオフライン扱い
STALE_SECONDS = 30
# 一覧に返す録画ファイルの上限（新しい順）
RECORDINGS_LIMIT = 300

CAMERA_IDS = ["cam1", "cam2", "cam3", "cam4"]

# streamer が書き出す常時録画ファイル名（streamer/stream.sh の -strftime 出力に対応）
RECORDING_RE = re.compile(r"^(\d{8})_(\d{6})\.mp4$")

app = FastAPI(title="SkyMonitor API")


def stream_status(camera_id: str) -> bool:
    playlist = HLS_ROOT / camera_id / "stream.m3u8"
    if not playlist.exists():
        return False
    age = time.time() - playlist.stat().st_mtime
    return age < STALE_SECONDS


def list_recordings(camera_id: str) -> list[dict]:
    cam_dir = RECORDINGS_ROOT / camera_id
    if not cam_dir.is_dir():
        return []

    events = []
    for entry in cam_dir.iterdir():
        if m := RECORDING_RE.match(entry.name):
            events.append(
                {
                    "camera_id": camera_id,
                    "timestamp": m.group(1) + m.group(2),
                    # 撮影終了時刻の目安として、ファイルの最終更新時刻(epoch秒)を返す
                    # 録画中（分割の最新ファイル）の場合は直近の書き込み時刻になる
                    "end_epoch": entry.stat().st_mtime,
                    "video": entry.name,
                }
            )

    events.sort(key=lambda e: e["timestamp"], reverse=True)
    return events


@app.get("/api/status")
def status() -> dict:
    cameras = []
    for i, camera_id in enumerate(CAMERA_IDS, start=1):
        label = os.environ.get(f"CAMERA_{i}_LABEL", f"カメラ{i}")
        cameras.append(
            {"id": camera_id, "label": label, "live": stream_status(camera_id)}
        )
    return {"cameras": cameras}


@app.get("/api/recordings")
def recordings() -> dict:
    events = []
    for camera_id in CAMERA_IDS:
        events.extend(list_recordings(camera_id))
    events.sort(key=lambda e: e["timestamp"], reverse=True)
    return {"events": events[:RECORDINGS_LIMIT], "total": len(events)}
