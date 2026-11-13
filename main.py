import mimetypes
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

HLS_ROOT = Path(os.environ.get("HLS_ROOT", "/hls"))
RECORDINGS_ROOT = Path(os.environ.get("RECORDINGS_ROOT", "/recordings"))
# 再接続の依頼を streamer に渡すためのディレクトリ（streamer と共有するボリューム）
CONTROL_ROOT = Path(os.environ.get("CONTROL_ROOT", "/control"))
WEB_ROOT = Path(os.environ.get("WEB_ROOT", Path(__file__).parent / "web"))
PLAYLIST_NAME = "stream.m3u8"

# Python 標準の mimetypes は .ts を登録していない（環境によっては TypeScript 扱い）ため明示する
mimetypes.add_type("application/vnd.apple.mpegurl", ".m3u8")
mimetypes.add_type("video/mp2t", ".ts")

# プレイリストの更新が止まってからこの秒数を超えたらオフライン扱い
STALE_SECONDS = 30
# 一覧に返す録画ファイルの上限（新しい順）
RECORDINGS_LIMIT = 300
# 「今すぐ保存」でダウンロードさせるクリップの長さ（秒）。streamer/stream.sh の
# SAVE_CLIP_SECONDS と揃える（.env の SAVE_CLIP_SECONDS で両方に反映される）
SAVE_CLIP_SECONDS = float(os.environ.get("SAVE_CLIP_SECONDS", "30"))
MIN_CLIP_SECONDS = 5.0

# 「今すぐ保存」はリクエストごとに ffmpeg を起動するため、閲覧者ごとに回数を制限する
# 平均 SAVE_RATE_PER_MINUTE 回/分、瞬間的には SAVE_BURST 回まで連続で受け付ける
SAVE_RATE_PER_MINUTE = float(os.environ.get("SAVE_RATE_PER_MINUTE", "6"))
SAVE_BURST = int(os.environ.get("SAVE_BURST", "4"))

# 「再接続」も公開ページから押せるため、閲覧者ごとに回数を制限する（平均 2 回/分、連続 2 回まで）
RECONNECT_RATE_PER_MINUTE = 2
RECONNECT_BURST = 2

# Cloudflare Tunnel 経由では接続元が常に cloudflared コンテナになるため、
# 接続元がこのホストのときに限り CF-Connecting-IP を本来の閲覧者として扱う
# （LAN から直接アクセスした場合はヘッダーを偽装されても無視される）
TRUSTED_PROXY_HOST = os.environ.get("TRUSTED_PROXY_HOST", "cloudflared")

CAMERA_IDS = [f"cam{i}" for i in range(1, 5)]

# streamer が書き出す常時録画ファイル名（streamer/stream.sh の -strftime 出力に対応）
RECORDING_RE = re.compile(r"^(\d{8})_(\d{6})\.mp4$")

app = FastAPI(title="SkyMonitor", docs_url=None, redoc_url=None, openapi_url=None)


class RateLimiter:
    """クライアントごとのトークンバケット（単一プロセス・メモリ内で管理）"""

    def __init__(self, rate_per_minute: float, burst: int) -> None:
        self.rate = rate_per_minute / 60.0
        self.burst = burst
        self.buckets: dict[str, tuple[float, float]] = {}  # key -> (残りトークン, 最終更新時刻)
        self.lock = threading.Lock()

    def acquire(self, key: str) -> float:
        """1 回分を消費できれば 0 を、できなければ再試行までの秒数を返す"""
        now = time.monotonic()
        with self.lock:
            self._prune(now)
            tokens, updated = self.buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - updated) * self.rate)
            if tokens < 1:
                self.buckets[key] = (tokens, now)
                return (1 - tokens) / self.rate
            self.buckets[key] = (tokens - 1, now)
            return 0.0

    def _prune(self, now: float) -> None:
        # 満タンまで回復したクライアントは記録しておく必要がないので捨てる
        full_after = self.burst / self.rate
        for key, (_, updated) in list(self.buckets.items()):
            if now - updated >= full_after:
                del self.buckets[key]


save_limiter = RateLimiter(SAVE_RATE_PER_MINUTE, SAVE_BURST)
reconnect_limiter = RateLimiter(RECONNECT_RATE_PER_MINUTE, RECONNECT_BURST)


def trusted_proxy_ip() -> str | None:
    try:
        return socket.gethostbyname(TRUSTED_PROXY_HOST)
    except OSError:
        # Tunnel を使っていない（cloudflared が起動していない）
        return None


def client_key(request: Request) -> str:
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("cf-connecting-ip")
    if forwarded and peer == trusted_proxy_ip():
        return forwarded
    return peer


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/hls/"):
        # ライブ配信なので（Cloudflare を含め）キャッシュさせない
        response.headers["Cache-Control"] = "no-cache, no-store"
    return response


def camera_label(index: int) -> str:
    return os.environ.get(f"CAMERA_{index}_LABEL", f"カメラ{index}")


def camera_enabled(index: int) -> bool:
    # docker-compose.yml が RTSP_URL_N の有無から設定する。未設定（ローカル開発）なら有効扱い
    return os.environ.get(f"CAMERA_{index}_ENABLED", "true") == "true"


# RTSP_URL が空のカメラをライブ画面から外して詰めるか（false なら「未設定」パネルとして残す）
HIDE_DISABLED_CAMERAS = os.environ.get("HIDE_DISABLED_CAMERAS", "true").lower() == "true"


def enabled_camera_ids() -> list[str]:
    return [cid for i, cid in enumerate(CAMERA_IDS, start=1) if camera_enabled(i)]


def playlist_path(camera_id: str) -> Path:
    return HLS_ROOT / camera_id / PLAYLIST_NAME


def is_live(camera_id: str) -> bool:
    try:
        mtime = playlist_path(camera_id).stat().st_mtime
    except FileNotFoundError:
        return False
    return time.time() - mtime < STALE_SECONDS


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
                    "end_epoch": entry.stat().st_mtime,
                    "video": entry.name,
                }
            )

    events.sort(key=lambda e: e["timestamp"], reverse=True)
    # 先頭（最新）のファイルは現在撮影中でまだ確定していないため一覧から除外する
    return events[1:]


def parse_playlist(playlist: Path) -> list[tuple[float, str]]:
    """HLS プレイリストから (再生時間, セグメントファイル名) を古い順に返す"""
    segments = []
    pending_duration = None
    for line in playlist.read_text().splitlines():
        line = line.strip()
        if line.startswith("#EXTINF:"):
            pending_duration = float(line.removeprefix("#EXTINF:").split(",")[0])
        elif line and not line.startswith("#") and pending_duration is not None:
            segments.append((pending_duration, line))
            pending_duration = None
    return segments


def recent_hls_segments(camera_id: str, seconds: float) -> list[Path]:
    """配信中の HLS から、直近 seconds 秒分のセグメントのパスを古い順に返す"""
    playlist = playlist_path(camera_id)
    try:
        segments = parse_playlist(playlist)
    except FileNotFoundError:
        return []

    chosen = []
    total = 0.0
    for duration, name in reversed(segments):
        chosen.append(playlist.parent / name)
        total += duration
        if total >= seconds:
            break
    chosen.reverse()
    return chosen


def concat_segments(segments: list[Path], output: Path) -> bool:
    concat_input = "concat:" + "|".join(str(p) for p in segments)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", concat_input, "-c", "copy", "-movflags", "+faststart", str(output)],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


@app.get("/api/status")
def status() -> dict:
    return {
        "hide_disabled": HIDE_DISABLED_CAMERAS,
        "cameras": [
            {
                "id": camera_id,
                "label": camera_label(i),
                "enabled": camera_enabled(i),
                "live": camera_enabled(i) and is_live(camera_id),
            }
            for i, camera_id in enumerate(CAMERA_IDS, start=1)
        ],
    }


@app.get("/api/recordings")
def recordings() -> dict:
    events = [e for camera_id in CAMERA_IDS for e in list_recordings(camera_id)]
    events.sort(key=lambda e: e["timestamp"], reverse=True)
    return {"events": events[:RECORDINGS_LIMIT]}


@app.post("/api/recordings/save")
def save_clip(
    request: Request, camera_id: str, seconds: float = SAVE_CLIP_SECONDS
) -> FileResponse:
    if camera_id not in enabled_camera_ids():
        raise HTTPException(status_code=404, detail="unknown camera_id")
    if retry_after := save_limiter.acquire(client_key(request)):
        raise HTTPException(
            status_code=429,
            detail="too many requests",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    seconds = max(MIN_CLIP_SECONDS, min(seconds, SAVE_CLIP_SECONDS))

    segments = recent_hls_segments(camera_id, seconds)
    if not segments:
        raise HTTPException(status_code=409, detail="no live segments available")

    # 録画一覧（/recordings）には残さず、その場でダウンロードさせるだけの一時ファイルとして書き出す
    # 同時刻に複数リクエストが来ても衝突しないよう、一意な一時ファイル名を使う
    fd, tmp_name = tempfile.mkstemp(prefix=f"skymonitor_{camera_id}_", suffix=".mp4")
    os.close(fd)
    tmp_path = Path(tmp_name)

    if not concat_segments(segments, tmp_path):
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="failed to save clip")

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return FileResponse(
        tmp_path,
        media_type="video/mp4",
        filename=f"{camera_id}_{ts}.mp4",
        background=BackgroundTask(tmp_path.unlink, missing_ok=True),
    )


@app.post("/api/cameras/{camera_id}/reconnect")
def reconnect(request: Request, camera_id: str) -> dict:
    if camera_id not in enabled_camera_ids():
        raise HTTPException(status_code=404, detail="unknown camera_id")
    if retry_after := reconnect_limiter.acquire(client_key(request)):
        raise HTTPException(
            status_code=429,
            detail="too many requests",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    # streamer は監視ループのたびにこのファイルを確認し、見つけたら消して ffmpeg を起動し直す
    CONTROL_ROOT.mkdir(parents=True, exist_ok=True)
    (CONTROL_ROOT / f"{camera_id}.reconnect").touch()
    return {"requested": True}


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


# 静的ファイルの配信（API のルートより後に登録すること。"/" は他のパスに一致しなかったものを受ける）
app.mount("/hls", StaticFiles(directory=HLS_ROOT, check_dir=False), name="hls")
app.mount("/recordings", StaticFiles(directory=RECORDINGS_ROOT, check_dir=False), name="recordings")
app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")
