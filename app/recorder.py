from __future__ import annotations

import asyncio
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


class VideoRecorder:
    """HLS ストリームを MP4 に変換する"""

    def __init__(self, hls_root: Path, output_dir: Path | None = None) -> None:
        self.hls_root = hls_root
        self.output_dir = output_dir or Path("records")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # セッション管理：{session_id: {cam_id: (proc, output_path)}}
        self.sessions: Dict[str, Dict[str, tuple[subprocess.Popen, Path]]] = {}

    def start_recording(self, camera_ids: List[str], cam_name_map: Dict[str, str] | None = None) -> str:
        """
        複数カメラから無期限で映像を録画開始

        Args:
            camera_ids: 録画対象のカメラID（例：["cam1", "cam2"]）
            cam_name_map: カメラID→カメラ名のマッピング（例：{"cam1": "Camera 1"}）

        Returns:
            session_id: セッションID（停止時に使用）
        """
        if cam_name_map is None:
            cam_name_map = {}
        session_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.sessions[session_id] = {}

        for cam_id in camera_ids:
            try:
                hls_m3u8 = self.hls_root / cam_id / "index.m3u8"
                if not hls_m3u8.exists():
                    print(f"HLS manifest not found for {cam_id}")
                    continue

                # カメラ名があればそれを使用、なければカメラIDを使用
                display_name = cam_name_map.get(cam_id, cam_id)
                output_path = self.output_dir / f"record_{display_name}_{timestamp}_{session_id}.mp4"

                cmd = [
                    "ffmpeg",
                    "-allowed_extensions",
                    "ALL",
                    "-i",
                    str(hls_m3u8),
                    "-c",
                    "copy",
                    "-bsf:a",
                    "aac_adtstoasc",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ]

                # ffmpeg をバックグラウンドで実行（期間制限なし）
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.sessions[session_id][cam_id] = (proc, output_path)
            except Exception as e:
                print(f"Error starting recording for {cam_id}: {e}")

        return session_id

    def stop_recording(self, session_id: str) -> Dict[str, Path]:
        """
        セッションの録画を停止

        Args:
            session_id: start_recording() が返したセッションID

        Returns:
            {cam_id: output_path} の辞書
        """
        session = self.sessions.pop(session_id, {})
        output_paths: Dict[str, Path] = {}

        for cam_id, (proc, output_path) in session.items():
            try:
                # ffmpeg プロセスを終了
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()

                # ファイルが存在することを確認
                if output_path.exists():
                    output_paths[cam_id] = output_path
                else:
                    print(f"Output file not created for {cam_id}: {output_path}")
            except Exception as e:
                print(f"Error stopping recording for {cam_id}: {e}")

        return output_paths

    async def record_cameras(
        self,
        camera_ids: List[str],
        duration_seconds: int = 600,
        cam_name_map: Dict[str, str] | None = None,
    ) -> Dict[str, Path]:
        """
        複数カメラから指定時間の映像を録画（レガシー用）

        Args:
            camera_ids: 録画対象のカメラID（例：["cam1", "cam2"]）
            duration_seconds: 録画時間（秒、デフォルト10分）
            cam_name_map: カメラID→カメラ名のマッピング（例：{"cam1": "Camera 1"}）

        Returns:
            {cam_id: output_path} の辞書
        """
        if cam_name_map is None:
            cam_name_map = {}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_paths: Dict[str, Path] = {}

        tasks = []
        for cam_id in camera_ids:
            # カメラ名があればそれを使用、なければカメラIDを使用
            display_name = cam_name_map.get(cam_id, cam_id)
            task = self._record_single_camera(
                cam_id, f"record_{display_name}_{timestamp}.mp4", duration_seconds
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for cam_id, result in zip(camera_ids, results):
            if isinstance(result, Path):
                output_paths[cam_id] = result
            elif isinstance(result, Exception):
                print(f"Error recording {cam_id}: {result}")

        return output_paths

    async def _record_single_camera(
        self, cam_id: str, filename: str, duration_seconds: int
    ) -> Path:
        """単一カメラの録画を実行"""
        hls_m3u8 = self.hls_root / cam_id / "index.m3u8"
        if not hls_m3u8.exists():
            raise FileNotFoundError(f"HLS manifest not found for {cam_id}")

        output_path = self.output_dir / filename

        cmd = [
            "ffmpeg",
            "-allowed_extensions",
            "ALL",
            "-t",
            str(duration_seconds),
            "-i",
            str(hls_m3u8),
            "-c",
            "copy",
            "-bsf:a",
            "aac_adtstoasc",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        # ffmpeg をバックグラウンドで実行
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 完了まで待機（タイムアウト付き）
        timeout = duration_seconds + 30  # 余裕を持たせる
        try:
            await asyncio.wait_for(
                asyncio.to_thread(proc.wait),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Recording timeout for {cam_id}")

        if output_path.exists():
            return output_path
        raise RuntimeError(f"Failed to record {cam_id}")

    def stop_all(self) -> None:
        """全セッションの録画を停止"""
        for session_id in list(self.sessions.keys()):
            self.stop_recording(session_id)

    def stop_camera(self, cam_id: str) -> None:
        """特定カメラの録画を停止"""
        proc = self.processes.pop(cam_id, None)
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass

    def stop_all(self) -> None:
        """全カメラの録画を停止"""
        for cam_id in list(self.processes.keys()):
            self.stop_camera(cam_id)
