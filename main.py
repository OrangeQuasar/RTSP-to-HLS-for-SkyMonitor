import os
import time
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

HLS_PORT = os.environ.get("HLS_PORT", "8888")
HLS_ROOT = Path(os.environ.get("HLS_ROOT", "/hls"))
# プレイリストの更新が止まってからこの秒数を超えたらオフライン扱い
STALE_SECONDS = 30

CAMERA_IDS = ["cam1", "cam2", "cam3", "cam4"]

st.set_page_config(page_title="SkyMonitor Live", page_icon="📡", layout="wide")
st.title("📡 SkyMonitor Live")


@dataclass
class Camera:
    id: str
    label: str
    live: bool


def stream_status(camera_id: str) -> bool:
    playlist = HLS_ROOT / camera_id / "stream.m3u8"
    if not playlist.exists():
        return False
    age = time.time() - playlist.stat().st_mtime
    return age < STALE_SECONDS


def load_cameras() -> list[Camera]:
    cameras = []
    for i, camera_id in enumerate(CAMERA_IDS, start=1):
        label = os.environ.get(f"CAMERA_{i}_LABEL", f"カメラ{i}")
        cameras.append(Camera(id=camera_id, label=label, live=stream_status(camera_id)))
    return cameras


cameras = load_cameras()
live_count = sum(c.live for c in cameras)
if live_count == len(cameras):
    st.success(f"配信中 — {live_count}/{len(cameras)} 台のカメラ映像を受信しています")
elif live_count > 0:
    st.warning(f"一部のカメラのみ配信中です（{live_count}/{len(cameras)} 台）。映像パネルの状態を確認してください。")
else:
    st.warning(
        "ストリームがまだ利用できません。カメラ接続中か、RTSP_URL の設定を確認してください。"
        "（数十秒待ってから下の再読み込みを押してください）"
    )

panels = ""
starts = ""
for i, cam in enumerate(cameras):
    dot_color = "#2ecc71" if cam.live else "#888"
    # 左列(1,3)は右寄せ・右列(2,4)は左寄せにして、中央の間隔を grid の gap だけにする
    justify = "flex-end" if i % 2 == 0 else "flex-start"
    panels += f"""
    <div style="display: flex; align-items: center; justify-content: {justify};
                min-width: 0; min-height: 0;">
      <div id="panel{i}" style="position: relative; background: #000; overflow: hidden;
                  height: 100%; max-width: 100%; aspect-ratio: 16 / 9;">
        <video id="video{i}" muted autoplay playsinline
               style="width: 100%; height: 100%; object-fit: contain; background: #000;"></video>
        <div style="position: absolute; top: 6px; left: 8px; padding: 2px 8px;
                    background: rgba(0,0,0,0.5); color: #fff; font-size: 13px;
                    border-radius: 4px; display: flex; align-items: center; gap: 6px;">
          <span style="width: 8px; height: 8px; border-radius: 50%; background: {dot_color};"></span>
          {cam.label}
        </div>
      </div>
    </div>
    """
    starts += f'  startPlayer("video{i}", "{cam.id}", "panel{i}");\n'

# HLS はブラウザから nginx (HLS_PORT) に直接取りに行くため、
# ホスト名はページの URL から動的に組み立てる
player_html = f"""
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.15/dist/hls.min.js"></script>
<div style="display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr;
            gap: 8px; height: 100vh; box-sizing: border-box;">
  {panels}
</div>
<script>
  // components.html は srcdoc 付き iframe に描画されるため、
  // window.location は about:srcdoc を指してしまう。
  // 親ページ (Streamlit 本体) の URL から組み立てる。
  const parentLoc = window.parent.location;
  const baseUrl = parentLoc.protocol + "//" + parentLoc.hostname + ":{HLS_PORT}";

  function startPlayer(videoId, cameraId, panelId) {{
    const video = document.getElementById(videoId);
    const panel = document.getElementById(panelId);
    const src = baseUrl + "/hls/" + cameraId + "/stream.m3u8";

    // パネルを映像の実アスペクト比に合わせ、黒帯（レターボックス）をなくす
    video.addEventListener("loadedmetadata", () => {{
      if (video.videoWidth && video.videoHeight) {{
        panel.style.aspectRatio = video.videoWidth + " / " + video.videoHeight;
      }}
    }});

    function createPlayer() {{
      const hls = new Hls({{
        liveSyncDurationCount: 3,
        maxLiveSyncPlaybackRate: 1.5,
      }});
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.ERROR, (event, data) => {{
        if (!data.fatal) return;
        // hls.js 推奨のエラー種別ごとの復旧処理
        // https://github.com/video-dev/hls.js/blob/master/docs/API.md#fatal-error-recovery
        switch (data.type) {{
          case Hls.ErrorTypes.NETWORK_ERROR:
            setTimeout(() => hls.startLoad(), 1000);
            break;
          case Hls.ErrorTypes.MEDIA_ERROR:
            hls.recoverMediaError();
            break;
          default:
            // 復旧不能なエラーはプレイヤーごと作り直す
            hls.destroy();
            setTimeout(createPlayer, 3000);
            break;
        }}
      }});
    }}

    if (Hls.isSupported()) {{
      createPlayer();
    }} else if (video.canPlayType("application/vnd.apple.mpegurl")) {{
      // Safari はネイティブ HLS 再生
      video.src = src;
    }}
  }}

{starts}
</script>
"""
components.html(player_html, height=720)

if st.button("再読み込み"):
    st.rerun()

st.caption(
    "RTSP → ffmpeg → HLS → hls.js で配信しています。"
    "HLS の特性上、実映像から数秒の遅延があります。"
)
