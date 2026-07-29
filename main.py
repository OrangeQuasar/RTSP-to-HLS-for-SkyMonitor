import os
import shutil
import subprocess
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from loguru import logger

RTSP_URL = os.environ.get("RTSP_URL", "")
RTSP_TRANSPORT = os.environ.get("RTSP_TRANSPORT", "tcp")
# カメラの映像コーデックが H.264 なら "copy"(無変換・低負荷)、
# H.265 などブラウザで再生できない場合は "libx264" を指定する
VIDEO_CODEC = os.environ.get("VIDEO_CODEC", "copy")

BASE_DIR = Path(__file__).resolve().parent
HLS_DIR = BASE_DIR / "static" / "hls"
PLAYLIST = HLS_DIR / "stream.m3u8"
PLAYLIST_URL = "/app/static/hls/stream.m3u8"

PLAYER_HTML = f"""
<script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script>
<video id="video" muted autoplay playsinline controls
       style="width: 100%; max-height: 70vh; background: #000;"></video>
<script>
  const video = document.getElementById("video");
  const src = "{PLAYLIST_URL}";
  if (Hls.isSupported()) {{
    const hls = new Hls({{
      liveSyncDurationCount: 2,
      liveMaxLatencyDurationCount: 6,
      maxBufferLength: 10,
    }});
    hls.loadSource(src);
    hls.attachMedia(video);
    hls.on(Hls.Events.ERROR, (event, data) => {{
      if (data.fatal) {{
        // 配信の一時中断などは 3 秒後にロードし直して復帰を試みる
        setTimeout(() => {{
          hls.destroy();
          location.reload();
        }}, 3000);
      }}
    }});
  }} else if (video.canPlayType("application/vnd.apple.mpegurl")) {{
    // Safari はネイティブで HLS を再生できる
    video.src = src;
  }}
</script>
"""


def build_ffmpeg_cmd() -> list[str]:
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-loglevel", "warning",
        "-rtsp_transport", RTSP_TRANSPORT,
        "-fflags", "nobuffer",
        "-i", RTSP_URL,
        "-an",
        "-c:v", VIDEO_CODEC,
    ]
    if VIDEO_CODEC != "copy":
        cmd += ["-preset", "veryfast", "-tune", "zerolatency", "-g", "30"]
    cmd += [
        "-f", "hls",
        "-hls_time", "1",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments+independent_segments",
        "-hls_segment_filename", str(HLS_DIR / "seg_%05d.ts"),
        str(PLAYLIST),
    ]
    return cmd


class FfmpegManager:
    """RTSP → HLS 変換を行う ffmpeg プロセスの管理。

    st.cache_resource でプロセス(サーバー)全体に 1 つだけ保持し、
    セッションやリランをまたいで同じ ffmpeg を使い回す。
    """

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.started_at: float = 0.0

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure_running(self) -> None:
        if self.is_running():
            return
        if self.proc is not None:
            logger.warning("ffmpeg が終了していたため再起動します (code={})", self.proc.returncode)
        shutil.rmtree(HLS_DIR, ignore_errors=True)
        HLS_DIR.mkdir(parents=True, exist_ok=True)
        cmd = build_ffmpeg_cmd()
        logger.info("ffmpeg を起動します: {}", " ".join(cmd))
        self.proc = subprocess.Popen(cmd)
        self.started_at = time.time()

    def restart(self) -> None:
        if self.is_running():
            assert self.proc is not None
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.ensure_running()


@st.cache_resource
def get_manager() -> FfmpegManager:
    return FfmpegManager()


def wait_for_playlist(timeout: float = 30.0) -> bool:
    """ffmpeg が最初のプレイリストを書き出すまで待つ。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if PLAYLIST.exists():
            return True
        time.sleep(0.5)
    return False


def main() -> None:
    st.set_page_config(page_title="SkyMonitor Live", page_icon="📷", layout="wide")
    st.title("📷 SkyMonitor ライブ映像")

    if not RTSP_URL:
        st.error("環境変数 `RTSP_URL` が設定されていません。`.env` を作成して docker compose を起動し直してください。")
        st.code("RTSP_URL=rtsp://user:pass@192.168.1.10:554/stream1", language="bash")
        st.stop()

    manager = get_manager()
    manager.ensure_running()

    with st.sidebar:
        st.subheader("ステータス")
        if manager.is_running():
            st.success(f"変換中 (稼働 {int(time.time() - manager.started_at)} 秒)")
        else:
            st.error("ffmpeg が停止しています")
        st.caption(f"転送: {RTSP_TRANSPORT} / コーデック: {VIDEO_CODEC}")
        if st.button("ストリームを再起動"):
            manager.restart()
            st.rerun()

    if not PLAYLIST.exists():
        with st.spinner("カメラに接続してストリームを準備しています..."):
            if not wait_for_playlist():
                st.error(
                    "ストリームを開始できませんでした。RTSP_URL が正しいか、"
                    "カメラに到達できるか確認してください。"
                    "(H.265 カメラの場合は `VIDEO_CODEC=libx264` を試してください)"
                )
                st.stop()

    components.html(PLAYER_HTML, height=600)
    st.caption("HLS 変換のため数秒の遅延があります。")


main()
