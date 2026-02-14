from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from loguru import logger

from .config import load_config, save_config, ensure_hls_root
from .rtsp import RtspManager
from .recorder import VideoRecorder

# loguru の設定
logger.remove()  # デフォルトハンドラーを削除
logger.add(sys.stderr, level="INFO")
logger.add(
    "logs/skymonitor.log",
    level="INFO",
    rotation="500 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
)

BASE_DIR = Path(__file__).resolve().parents[1]

app = FastAPI()
# セッション用の秘密鍵を環境変数から取得（本番環境では必ず設定）
session_secret_key = os.getenv("SESSION_SECRET_KEY", "change-me-in-production")
app.add_middleware(SessionMiddleware, secret_key=session_secret_key)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    config = load_config()
    hls_root = ensure_hls_root(config)
    
    logger.info("=== SkyMonitor Startup ===")
    logger.info(f"HLS Root: {hls_root}")
    logger.info(f"Enabled cameras: {[cam.get('id') for cam in config.get('cameras', []) if cam.get('enabled') and cam.get('rtsp_url')]}")
    
    app.state.rtsp_manager = RtspManager(hls_root)
    app.state.rtsp_manager.apply_config(config)
    app.state.recorder = VideoRecorder(hls_root, output_dir=Path("records"))
    
    logger.info("=== Startup Complete ===")


@app.get("/")
def index(request: Request):
    config = load_config()
    cameras = _normalize_cameras(config.get("cameras", []))
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "layout": "2x2",
            "cameras": cameras,
        },
    )


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(request: Request, password: str = Form("")):
    config = load_config()
    if password == config.get("admin_password"):
        request.session["is_admin"] = True
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid password"},
        status_code=401,
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/admin")
def admin_page(request: Request):
    redirect = _require_admin(request)
    if redirect:
        return redirect
    config = load_config()
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "config": config},
    )


@app.post("/admin")
async def admin_save(
    request: Request,
):
    redirect = _require_admin(request)
    if redirect:
        return redirect
    config = load_config()
    form = await request.form()

    if "layout" in form:
        config["layout"] = form.get("layout") or config.get("layout", "2x2")

    admin_password = form.get("admin_password")
    if admin_password:
        config["admin_password"] = admin_password

    existing_by_id = {cam.get("id"): cam for cam in config.get("cameras", [])}

    cameras: List[Dict[str, Any]] = []
    for idx in range(1, 5):
        cam_id = f"cam{idx}"
        existing = existing_by_id.get(cam_id, {})
        cameras.append(
            {
                "id": cam_id,
                "name": form.get(f"name_{idx}") or existing.get("name") or f"Camera {idx}",
                "rtsp_url": form.get(f"rtsp_{idx}") or existing.get("rtsp_url") or "",
                "enabled": True,
                "width": int(existing.get("width") or 1280),
                "height": int(existing.get("height") or 720),
                "fps": int(existing.get("fps") or 15),
            }
        )

    config["cameras"] = cameras
    save_config(config)

    app.state.rtsp_manager.apply_config(config)
    return RedirectResponse(url="/admin", status_code=303)


def _require_admin(request: Request) -> RedirectResponse | None:
    if not request.session.get("is_admin"):
        return RedirectResponse(url="/login", status_code=303)
    return None


def _normalize_cameras(cameras: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {cam.get("id"): cam for cam in cameras}
    normalized: List[Dict[str, Any]] = []
    for idx in range(1, 5):
        cam_id = f"cam{idx}"
        existing = by_id.get(cam_id, {})
        normalized.append(
            {
                "id": cam_id,
                "name": existing.get("name") or f"Camera {idx}",
                "rtsp_url": existing.get("rtsp_url") or "",
            }
        )
    return normalized


@app.get("/api/status")
async def get_status(request: Request) -> Dict[str, Any]:
    """
    システム状態とFFmpegプロセスの確認（デバッグ用）
    """
    config = load_config()
    rtsp_manager: RtspManager = app.state.rtsp_manager
    hls_root = Path(config.get("hls_root") or "hls")
    if not hls_root.is_absolute():
        hls_root = Path(__file__).resolve().parents[1] / hls_root
    
    camera_status = []
    for cam in config.get("cameras", []):
        cam_id = cam.get("id")
        cam_name = cam.get("name", cam_id)
        rtsp_url = cam.get("rtsp_url", "").strip()
        is_enabled = cam.get("enabled", False)
        
        # HLSファイルの確認
        m3u8_path = hls_root / cam_id / "index.m3u8"
        m3u8_exists = m3u8_path.exists()
        
        # FFmpegプロセスの確認
        proc = rtsp_manager.processes.get(cam_id)
        proc_running = proc is not None and proc.poll() is None
        
        # FFmpegログファイルの確認
        ffmpeg_log = hls_root / cam_id / "ffmpeg.log"
        ffmpeg_log_content = ""
        if ffmpeg_log.exists():
            try:
                ffmpeg_log_content = ffmpeg_log.read_text()[-500:]  # 最後の500文字
            except:
                ffmpeg_log_content = "(Failed to read log)"
        
        camera_status.append({
            "id": cam_id,
            "name": cam_name,
            "enabled": is_enabled,
            "rtsp_url": rtsp_url[:50] + "..." if len(rtsp_url) > 50 else rtsp_url,
            "ffmpeg_running": proc_running,
            "ffmpeg_pid": proc.pid if proc else None,
            "m3u8_exists": m3u8_exists,
            "ffmpeg_log_tail": ffmpeg_log_content if ffmpeg_log_content else "(No log)",
        })
    
    return {
        "status": "ok",
        "hls_root": str(hls_root),
        "hls_root_exists": hls_root.exists(),
        "cameras": camera_status,
    }


@app.post("/api/record")
async def start_recording(request: Request) -> Dict[str, Any]:
    """
    10分間の映像を全接続カメラから録画開始
    レスポンス：{status: "recording", files: {cam1: "filename", cam2: "filename"}}
    """
    try:
        config = load_config()
        cameras = config.get("cameras", [])
        enabled_ids = [
            cam.get("id")
            for cam in cameras
            if cam.get("enabled") and cam.get("rtsp_url")
        ]
        # カメラID→カメラ名のマッピングを作成
        cam_name_map = {
            cam.get("id"): cam.get("name", cam.get("id"))
            for cam in cameras
            if cam.get("enabled") and cam.get("rtsp_url")
        }

        if not enabled_ids:
            return {"status": "error", "message": "No cameras available"}

        # 10分（600秒）の録画を実行
        recorder: VideoRecorder = app.state.recorder
        output_paths = await recorder.record_cameras(enabled_ids, duration_seconds=600, cam_name_map=cam_name_map)

        # クライアント用にファイル名をマッピング
        files = {cam_id: path.name for cam_id, path in output_paths.items()}

        return {"status": "success", "files": files}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/record-start")
async def record_start(request: Request) -> Dict[str, Any]:
    """
    複数カメラから無期限で映像を録画開始
    レスポンス：{status: "recording", session_id: "abc123"}
    """
    try:
        config = load_config()
        cameras = config.get("cameras", [])
        enabled_ids = [
            cam.get("id")
            for cam in cameras
            if cam.get("enabled") and cam.get("rtsp_url")
        ]
        # カメラID→カメラ名のマッピングを作成
        cam_name_map = {
            cam.get("id"): cam.get("name", cam.get("id"))
            for cam in cameras
            if cam.get("enabled") and cam.get("rtsp_url")
        }

        if not enabled_ids:
            return {"status": "error", "message": "No cameras available"}

        # 無期限で録画開始
        recorder: VideoRecorder = app.state.recorder
        session_id = recorder.start_recording(enabled_ids, cam_name_map=cam_name_map)

        return {"status": "success", "session_id": session_id}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/record-stop/{session_id}")
async def record_stop(session_id: str, request: Request) -> Dict[str, Any]:
    """
    セッションの録画を停止
    レスポンス：{status: "success", files: {cam1: "filename", cam2: "filename"}}
    """
    try:
        recorder: VideoRecorder = app.state.recorder
        output_paths = recorder.stop_recording(session_id)

        # クライアント用にファイル名をマッピング
        files = {cam_id: path.name for cam_id, path in output_paths.items()}

        return {"status": "success", "files": files}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/download/{filename}")
async def download_file(filename: str) -> FileResponse:
    """
    録画ファイルをダウンロード
    """
    records_dir = Path("records")
    file_path = records_dir / filename

    # セキュリティ：パストトラバーサル対策
    if not file_path.resolve().parent == records_dir.resolve():
        return {"status": "error", "message": "Invalid filename"}

    if not file_path.exists():
        return {"status": "error", "message": "File not found"}

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="video/mp4",
    )
