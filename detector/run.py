"""SkyMonitor 用の流星検出ランナー（meteor-detect の atomcam.py を使う）

カメラ1台につき1つ起動し、夜間（METEOR_START_HOUR〜METEOR_END_HOUR 時、日本時間）だけ
RTSP を受信して流星を検出する。検出すると /meteors/<CAMERA_NAME>/ に次のファイルを書き出す。

- yyyymmddhhmmss.jpg       検出時の比較明合成画像（時刻は日本時間）
- movie-yyyymmddhhmmss.mp4 検出時の動画（ブラウザで再生できるよう H.264 に変換する）

atomcam.py 自体は変更せず、動画の保存だけをこのファイルで差し替えている。
"""

import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import atomcam

CAMERA_NAME = os.environ.get("CAMERA_NAME", "cam")
RTSP_URL = os.environ.get("RTSP_URL", "")
ENABLED = os.environ.get("METEOR_DETECT", "true").lower() == "true"
OUTPUT_DIR = Path(os.environ.get("METEORS_ROOT", "/meteors"), CAMERA_NAME)

# 検出する時間帯（0-23 時、日本時間）。開始より終了が小さければ日をまたぐ（例: 18〜翌6時）
START_HOUR = int(os.environ.get("METEOR_START_HOUR", "18"))
END_HOUR = int(os.environ.get("METEOR_END_HOUR", "6"))
# 流星とみなす線の最短の長さ（ピクセル）。長くすると誤検出は減るが短い流星を見落とす
MIN_LENGTH = int(os.environ.get("METEOR_MIN_LENGTH", "30"))
# 何秒分のフレームをまとめて判定するか
EXPOSURE_SECONDS = int(os.environ.get("METEOR_EXPOSURE_SECONDS", "1"))

# カメラに接続できなかったときに、もう一度試すまでの時間（秒）
RETRY_SECONDS = 30

def log(message: str) -> None:
    # atomcam.py は標準出力を検出ログに使うので、こちらは標準エラーに出す
    print(f"[detector:{CAMERA_NAME}] {message}", file=sys.stderr, flush=True)


def in_window(now: datetime) -> bool:
    if START_HOUR <= END_HOUR:
        return START_HOUR <= now.hour < END_HOUR
    return now.hour >= START_HOUR or now.hour < END_HOUR


def next_start(now: datetime) -> datetime:
    start = now.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
    return start if start > now else start + timedelta(days=1)


class SkyMonitorDetector(atomcam.AtomCam):
    """atomcam.AtomCam の動画保存だけを差し替えたもの"""

    def save_movie(self, img_list, pathname):
        # OpenCV が書ける mp4v はブラウザで再生できないので、一時ファイルに書いてから
        # ffmpeg で H.264 に変換する。完成したものだけが最終的なファイル名になるようにする
        final = Path(pathname)
        raw = final.with_name(f".raw-{final.name}")
        converted = final.with_name(f".h264-{final.name}")
        super().save_movie(img_list, str(raw))
        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(converted)],
            capture_output=True,
            check=False,
        )
        raw.unlink(missing_ok=True)
        if result.returncode == 0:
            converted.rename(final)
        else:
            converted.unlink(missing_ok=True)
            log(f"failed to convert movie: {result.stderr.decode(errors='replace').strip()}")


def run_one_night() -> None:
    """カメラに接続し、終了時刻（END_HOUR 時）まで検出を続ける"""
    try:
        detector = SkyMonitorDetector(
            RTSP_URL,
            output=str(OUTPUT_DIR),
            end_time=f"{END_HOUR:02d}00",
            minLineLength=MIN_LENGTH,
        )
    except (RuntimeError, FileNotFoundError) as e:
        log(f"cannot open camera: {e}. retrying in {RETRY_SECONDS}s")
        time.sleep(RETRY_SECONDS)
        return
    detector.run(EXPOSURE_SECONDS, no_window=True)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format=f"[detector:{CAMERA_NAME}] %(levelname)s: %(message)s")

    if not RTSP_URL or not ENABLED:
        # streamer と同じく、終了すると再起動を繰り返すので待機だけする
        log("camera disabled or METEOR_DETECT=false. idle.")
        while True:
            time.sleep(3600)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log(f"detecting meteors {START_HOUR:02d}:00-{END_HOUR:02d}:00 (min_length={MIN_LENGTH})")
    while True:
        now = datetime.now()
        if in_window(now):
            run_one_night()
        else:
            wait = (next_start(now) - now).total_seconds()
            log(f"outside detection hours. waiting until {next_start(now):%Y-%m-%d %H:%M}")
            time.sleep(wait)


if __name__ == "__main__":
    main()
