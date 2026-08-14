import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

HLS_ROOT = Path(os.environ.get("HLS_ROOT", "/hls"))
RECORDINGS_ROOT = Path(os.environ.get("RECORDINGS_ROOT", "/recordings"))
# プレイリストの更新が止まってからこの秒数を超えたらオフライン扱い
STALE_SECONDS = 30
# 一覧に返す録画ファイルの上限（新しい順）
RECORDINGS_LIMIT = 300
# 「今すぐ保存」でダウンロードさせるクリップの長さ（秒）。streamer/stream.sh の
# SAVE_CLIP_SECONDS と揃える（.env の SAVE_CLIP_SECONDS で両方に反映される）
SAVE_CLIP_SECONDS = float(os.environ.get("SAVE_CLIP_SECONDS", "30"))

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
    # 先頭（最新）のファイルは現在撮影中でまだ確定していないため一覧から除外する
    return events[1:]


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


def recent_hls_segments(camera_id: str, seconds: float) -> list[str]:
    """配信中のHLSプレイリストから、直近 seconds 秒分のセグメントファイル名を古い順に返す"""
    playlist = HLS_ROOT / camera_id / "stream.m3u8"
    if not playlist.exists():
        return []

    segments = []  # (duration, filename)
    pending_duration = None
    for line in playlist.read_text().splitlines():
        line = line.strip()
        if line.startswith("#EXTINF:"):
            pending_duration = float(line.removeprefix("#EXTINF:").rstrip(",").split(",")[0])
        elif line and not line.startswith("#") and pending_duration is not None:
            segments.append((pending_duration, line))
            pending_duration = None

    chosen = []
    total = 0.0
    for duration, name in reversed(segments):
        chosen.append(name)
        total += duration
        if total >= seconds:
            break
    chosen.reverse()
    return chosen


@app.post("/api/recordings/save")
def save_clip(camera_id: str, seconds: float = SAVE_CLIP_SECONDS) -> FileResponse:
    if camera_id not in CAMERA_IDS:
        raise HTTPException(status_code=404, detail="unknown camera_id")
    seconds = max(5.0, min(seconds, SAVE_CLIP_SECONDS))

    segment_names = recent_hls_segments(camera_id, seconds)
    if not segment_names:
        raise HTTPException(status_code=409, detail="no live segments available")

    # 録画一覧（/recordings）には残さず、その場でダウンロードさせるだけの一時ファイルとして書き出す
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    download_name = f"{camera_id}_{ts}.mp4"
    tmp_path = Path(tempfile.gettempdir()) / f"skymonitor_save_{camera_id}_{ts}.mp4"

    segment_paths = [str(HLS_ROOT / camera_id / name) for name in segment_names]
    concat_input = "concat:" + "|".join(segment_paths)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", concat_input, "-c", "copy", "-movflags", "+faststart", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="failed to save clip")

    return FileResponse(
        tmp_path,
        media_type="video/mp4",
        filename=download_name,
        background=BackgroundTask(tmp_path.unlink, missing_ok=True),
    )
