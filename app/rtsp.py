from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any

from loguru import logger


class RtspManager:
    def __init__(self, hls_root: Path) -> None:
        self.hls_root = hls_root
        self.processes: Dict[str, subprocess.Popen] = {}

    def apply_config(self, config: Dict[str, Any]) -> None:
        self.stop_all()
        self.hls_root = self._resolve_hls_root(config)
        logger.info(f"HLS root: {self.hls_root}")
        for camera in config.get("cameras", []):
            if camera.get("enabled"):
                self.start_camera(camera)

    def start_camera(self, camera: Dict[str, Any]) -> None:
        cam_id = camera.get("id")
        cam_name = camera.get("name", cam_id)
        if not cam_id or cam_id in self.processes:
            logger.warning(f"Camera {cam_name} ({cam_id}) already running or invalid ID")
            return
        rtsp_url = (camera.get("rtsp_url") or "").strip()
        if not rtsp_url:
            logger.warning(f"Camera {cam_name} ({cam_id}): No RTSP URL configured")
            return
        
        output_dir = self.hls_root / cam_id
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        playlist_path = output_dir / "index.m3u8"
        
        width = int(camera.get("width") or 1280)
        height = int(camera.get("height") or 720)
        fps = int(camera.get("fps") or 15)
        gop = max(1, fps * 2)

        cmd = [
            "ffmpeg",
            "-rtsp_transport",
            "tcp",
            "-i",
            rtsp_url,
            "-vf",
            f"scale={width}:{height}",
            "-r",
            str(fps),
            "-an",
            "-c:v",
            "libx264",
            "-g",
            str(gop),
            "-keyint_min",
            str(gop),
            "-sc_threshold",
            "0",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-f",
            "hls",
            "-hls_time",
            "2",
            "-hls_list_size",
            "6",
            "-hls_flags",
            "delete_segments+append_list+independent_segments",
            str(playlist_path),
        ]

        logger.info(f"Starting camera {cam_name} ({cam_id}) -> {playlist_path}")
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        
        # FFmpeg のエラー出力をキャプチャ
        log_file = output_dir / "ffmpeg.log"
        try:
            with open(log_file, "w") as log_f:
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    creationflags=self._creationflags(),
                )
                self.processes[cam_id] = proc
                logger.info(f"Camera {cam_name} ({cam_id}) FFmpeg process started (PID: {proc.pid})")
        except Exception as e:
            logger.error(f"Failed to start FFmpeg for {cam_name} ({cam_id}): {e}")

    def stop_all(self) -> None:
        for cam_id, proc in list(self.processes.items()):
            try:
                logger.info(f"Stopping camera {cam_id} (PID: {proc.pid})")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"Camera {cam_id} did not terminate, killing...")
                    proc.kill()
            except Exception as e:
                logger.error(f"Error stopping camera {cam_id}: {e}")
            finally:
                self.processes.pop(cam_id, None)

    def _resolve_hls_root(self, config: Dict[str, Any]) -> Path:
        hls_root = Path(config.get("hls_root") or "hls")
        if not hls_root.is_absolute():
            hls_root = self.hls_root.parent / hls_root
        hls_root.mkdir(parents=True, exist_ok=True)
        return hls_root

    @staticmethod
    def _creationflags() -> int:
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            return subprocess.CREATE_NEW_PROCESS_GROUP
        return 0
