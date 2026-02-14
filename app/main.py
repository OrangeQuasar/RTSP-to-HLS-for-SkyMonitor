from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import load_config, save_config, ensure_hls_root
from .rtsp import RtspManager
from .recorder import VideoRecorder

class StatusCodeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "200" not in str(record.getMessage())

uvicorn_logger = logging.getLogger("uvicorn.access")
uvicorn_logger.addFilter(StatusCodeFilter())

BASE_DIR = Path(__file__).resolve().parents[1]

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="change-me")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    config = load_config()
    hls_root = ensure_hls_root(config)
    app.state.rtsp_manager = RtspManager(hls_root)
    app.state.rtsp_manager.apply_config(config)
    app.state.recorder = VideoRecorder(hls_root, output_dir=Path("records"))


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
