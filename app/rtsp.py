from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any


class RtspManager:
    def __init__(self, hls_root: Path) -> None:
        self.hls_root = hls_root
        self.processes: Dict[str, subprocess.Popen] = {}

    def apply_config(self, config: Dict[str, Any]) -> None:
        self.stop_all()
        self.hls_root = self._resolve_hls_root(config)
        for camera in config.get("cameras", []):
            if camera.get("enabled"):
                self.start_camera(camera)

    def start_camera(self, camera: Dict[str, Any]) -> None:
        cam_id = camera.get("id")
        if not cam_id or cam_id in self.processes:
            return
        rtsp_url = (camera.get("rtsp_url") or "").strip()
        if not rtsp_url:
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

        self.processes[cam_id] = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=self._creationflags(),
        )

    def stop_all(self) -> None:
        for cam_id, proc in list(self.processes.items()):
            try:
                proc.terminate()
            except Exception:
                pass
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
