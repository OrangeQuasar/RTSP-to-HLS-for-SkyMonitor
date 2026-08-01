import os
import re
import time
from pathlib import Path

from fastapi import FastAPI

HLS_ROOT = Path(os.environ.get("HLS_ROOT", "/hls"))
RECORDINGS_ROOT = Path(os.environ.get("RECORDINGS_ROOT", "/recordings"))
# プレイリストの更新が止まってからこの秒数を超えたらオフライン扱い
STALE_SECONDS = 30
# ギャラリーに返す検出イベントの上限（新しい順）
RECORDINGS_LIMIT = 300

CAMERA_IDS = ["cam1", "cam2", "cam3", "cam4"]

# meteor-detect (atomcam.py) の出力ファイル名
# 合成検出画像: yyyymmddhhmmss.jpg / クリップ動画: movie-yyyymmddhhmmss.mp4
IMAGE_RE = re.compile(r"^(\d{14})\.jpg$")
MOVIE_RE = re.compile(r"^movie-(\d{14})\.mp4$")

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

    images: dict[str, str] = {}
    videos: dict[str, str] = {}
    for entry in cam_dir.iterdir():
        if m := IMAGE_RE.match(entry.name):
            images[m.group(1)] = entry.name
        elif m := MOVIE_RE.match(entry.name):
            videos[m.group(1)] = entry.name

    timestamps = sorted(images.keys() | videos.keys(), reverse=True)
    return [
        {
            "camera_id": camera_id,
            "timestamp": ts,
            "image": images.get(ts),
            "video": videos.get(ts),
        }
        for ts in timestamps
    ]


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
