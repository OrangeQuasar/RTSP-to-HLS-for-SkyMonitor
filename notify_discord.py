"""SkyMonitor の出来事を Discord に通知する

- カメラの接続が切れたとき・復旧したとき（api の /api/status を定期的に確認）
- cloudflared（Quick Tunnel）が公開 URL を発行したとき（cloudflared のメトリクスを確認）。
  スマートフォンで読み取れるよう、ライブ映像の URL の QR コード画像も添付する

通知の種類ごとに送信先の Webhook を分けられる。個別の Webhook が未設定なら DISCORD_WEBHOOK_URL に送り、
それも未設定なら送信せずログに出力するだけにする。
"""

import io
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import segno

# 共通の送信先（下の2つが未設定のときに使う）
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
# 公開 URL（Web リンク）の送信先
DISCORD_LINK_WEBHOOK_URL = os.environ.get("DISCORD_LINK_WEBHOOK_URL") or DISCORD_WEBHOOK_URL
# カメラの切断・復旧（ステータス）の送信先
DISCORD_STATUS_WEBHOOK_URL = os.environ.get("DISCORD_STATUS_WEBHOOK_URL") or DISCORD_WEBHOOK_URL
API_URL = os.environ.get("API_URL", "http://api:8000")
# cloudflared の --metrics で指定したアドレス（docker-compose.yml と揃える）
CLOUDFLARED_METRICS_URL = os.environ.get("CLOUDFLARED_METRICS_URL", "http://cloudflared:2000")
POLL_INTERVAL_SECONDS = 10
# この秒数以上オフラインが続いたら切断とみなす（ffmpeg の再起動などによる一瞬の途切れでは通知しない）
OFFLINE_GRACE_SECONDS = 30
JST = timezone(timedelta(hours=9))
# Discord（の手前の Cloudflare）は Python 既定の User-Agent を拒否することがあるため明示する
USER_AGENT = "SkyMonitor-Notifier (https://github.com/OrangeQuasar/RTSP-to-HLS-for-SkyMonitor, 1.0)"

FETCH_ERRORS = (urllib.error.URLError, OSError, ValueError)


def log(message: str) -> None:
    print(f"[notifier] {message}", flush=True)


def request(
    url: str, data: dict | None = None, files: dict[str, bytes] | None = None
) -> bytes:
    """GET（data なし）か、JSON を POST する。files があれば画像を添付した multipart で送る"""
    headers = {"User-Agent": USER_AGENT}
    if files:
        body, headers["Content-Type"] = multipart(data or {}, files)
    elif data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    else:
        body = None
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as res:
        return res.read()


def multipart(payload: dict, files: dict[str, bytes]) -> tuple[bytes, str]:
    """Discord の Webhook にファイルを添付するための multipart/form-data を作る

    メッセージ本文は payload_json に、ファイルは files[0], files[1], ... に入れる
    """
    boundary = f"skymonitor-{time.time_ns()}"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        "Content-Type: application/json\r\n\r\n".encode()
        + json.dumps(payload).encode()
    ]
    for i, (filename, content) in enumerate(files.items()):
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files[{i}]"; '
            f'filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode()
            + content
        )
    body = b"\r\n".join(parts) + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def send(webhook_url: str, message: str, files: dict[str, bytes] | None = None) -> bool:
    """Discord に送信する（files: ファイル名 → PNG 画像）。送信できた（または送信先が未設定）なら True"""
    log(message.replace("\n", " | "))
    if not webhook_url:
        return True
    try:
        request(webhook_url, {"content": message}, files)
    except (urllib.error.URLError, OSError) as e:
        log(f"failed to send to Discord: {e}")
        return False
    return True


def qr_png(text: str) -> bytes:
    """text を読み取れる QR コードの PNG 画像を作る"""
    buf = io.BytesIO()
    # scale: 1マスの大きさ（ピクセル）、border: 周りの余白（マス）
    segno.make(text, error="m").save(buf, kind="png", scale=8, border=4)
    return buf.getvalue()


def now_label() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


class CameraMonitor:
    """カメラごとのライブ状態を追跡し、切断・復旧を通知する

    起動直後は各カメラが接続されるまでオフラインに見えるため、一度ライブになったカメラだけを対象にする。
    復旧の通知は、切断を通知したカメラに対してのみ送る。
    """

    def __init__(self) -> None:
        self.seen_live: set[str] = set()
        self.offline_since: dict[str, float] = {}
        self.notified_down: set[str] = set()

    def check(self) -> None:
        try:
            cameras = json.loads(request(f"{API_URL}/api/status"))["cameras"]
        except (*FETCH_ERRORS, KeyError):
            # api 自体が落ちている・再起動中のときは判定しない
            return

        now = time.monotonic()
        for cam in cameras:
            if cam.get("enabled", True):
                self._update(cam["id"], cam["label"], bool(cam["live"]), now)

    def _update(self, cam_id: str, label: str, live: bool, now: float) -> None:
        if live:
            self.seen_live.add(cam_id)
            self.offline_since.pop(cam_id, None)
            if cam_id in self.notified_down and send(
                DISCORD_STATUS_WEBHOOK_URL,
                f"✅ {label} の接続が復旧しました（{now_label()}）"
            ):
                self.notified_down.discard(cam_id)
            return

        if cam_id not in self.seen_live or cam_id in self.notified_down:
            return
        since = self.offline_since.setdefault(cam_id, now)
        if now - since >= OFFLINE_GRACE_SECONDS and send(
            DISCORD_STATUS_WEBHOOK_URL,
            f"⚠️ {label} の接続が切断されました（{now_label()}）"
        ):
            self.notified_down.add(cam_id)


class TunnelMonitor:
    """cloudflared が発行した公開 URL が変わるたびに通知する"""

    def __init__(self) -> None:
        self.notified_url: str | None = None

    def check(self) -> None:
        url = self._current_url()
        if url and url != self.notified_url:
            live_url = f"{url}/"
            message = (
                "新しい SkyMonitor の公開 URL が発行されました！\n"
                f"ライブ映像: {live_url}\n"
#                f"アーカイブ: {url}/gallery.html"
            )
            # 送信に失敗した場合は次の周期で再送する
            if send(DISCORD_LINK_WEBHOOK_URL, message, {"skymonitor-qr.png": qr_png(live_url)}):
                self.notified_url = url

    @staticmethod
    def _current_url() -> str | None:
        """トンネルが接続済みなら公開 URL を、まだ（または tunnel を使っていない）なら None を返す"""
        try:
            # /ready はトンネルの接続が確立するまで 200 以外を返す
            request(f"{CLOUDFLARED_METRICS_URL}/ready")
            hostname = json.loads(request(f"{CLOUDFLARED_METRICS_URL}/quicktunnel")).get("hostname")
        except FETCH_ERRORS:
            return None
        return f"https://{hostname}" if hostname else None


def main() -> None:
    if not DISCORD_LINK_WEBHOOK_URL:
        log("no webhook for tunnel links. they are logged only.")
    if not DISCORD_STATUS_WEBHOOK_URL:
        log("no webhook for camera status. it is logged only.")

    monitors = [CameraMonitor(), TunnelMonitor()]
    while True:
        for monitor in monitors:
            monitor.check()
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
