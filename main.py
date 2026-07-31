import os
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

HLS_PORT = os.environ.get("HLS_PORT", "8888")
HLS_PLAYLIST = Path(os.environ.get("HLS_PLAYLIST", "/hls/stream.m3u8"))
# プレイリストの更新が止まってからこの秒数を超えたらオフライン扱い
STALE_SECONDS = 30

st.set_page_config(page_title="SkyMonitor Live", page_icon="📡", layout="wide")
st.title("📡 SkyMonitor Live")


def stream_status() -> tuple[bool, float | None]:
    if not HLS_PLAYLIST.exists():
        return False, None
    age = time.time() - HLS_PLAYLIST.stat().st_mtime
    return age < STALE_SECONDS, age


live, age = stream_status()
if live:
    st.success("配信中 — カメラ映像を受信しています")
else:
    st.warning(
        "ストリームがまだ利用できません。カメラ接続中か、RTSP_URL の設定を確認してください。"
        "（数十秒待ってから下の再読み込みを押してください）"
    )

# HLS はブラウザから nginx (HLS_PORT) に直接取りに行くため、
# ホスト名はページの URL から動的に組み立てる
player_html = f"""
<script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.15/dist/hls.min.js"></script>
<video id="video" muted autoplay playsinline controls
       style="width: 100%; max-height: 75vh; background: #000;"></video>
<script>
  // components.html は srcdoc 付き iframe に描画されるため、
  // window.location は about:srcdoc を指してしまう。
  // 親ページ (Streamlit 本体) の URL から組み立てる。
  const parentLoc = window.parent.location;
  const src = parentLoc.protocol + "//" + parentLoc.hostname
            + ":{HLS_PORT}/hls/stream.m3u8";
  const video = document.getElementById("video");
  if (Hls.isSupported()) {{
    const hls = new Hls({{
      liveSyncDurationCount: 2,
      maxLiveSyncPlaybackRate: 1.5,
      lowLatencyMode: true,
    }});
    hls.loadSource(src);
    hls.attachMedia(video);
    hls.on(Hls.Events.ERROR, (event, data) => {{
      if (data.fatal) {{
        // 配信が一時的に途切れても自動で再接続する
        setTimeout(() => {{ hls.loadSource(src); hls.startLoad(); }}, 3000);
      }}
    }});
  }} else if (video.canPlayType("application/vnd.apple.mpegurl")) {{
    // Safari はネイティブ HLS 再生
    video.src = src;
  }}
</script>
"""
components.html(player_html, height=650)

if st.button("再読み込み"):
    st.rerun()

st.caption(
    "RTSP → ffmpeg → HLS → hls.js で配信しています。"
    "HLS の特性上、実映像から数秒の遅延があります。"
)
