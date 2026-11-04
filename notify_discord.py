"""cloudflared（Quick Tunnel）が発行した URL を Discord に通知する

cloudflared のメトリクスサーバーを定期的に確認し、トンネルが接続済みで
URL が前回通知したものから変わっていれば Discord の Webhook に送信する。
cloudflared が再起動して URL が変わった場合も自動で通知される。
"""

import json
import os
import time
import urllib.error
import urllib.request

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
# cloudflared の --metrics で指定したアドレス（docker-compose.yml と揃える）
CLOUDFLARED_METRICS_URL = os.environ.get("CLOUDFLARED_METRICS_URL", "http://cloudflared:2000")
POLL_INTERVAL_SECONDS = 10
# Discord（の手前の Cloudflare）は Python 既定の User-Agent を拒否することがあるため明示する
USER_AGENT = "SkyMonitor-Notifier (https://github.com/OrangeQuasar/RTSP-to-HLS-for-SkyMonitor, 1.0)"


def log(message: str) -> None:
    print(f"[notifier] {message}", flush=True)


def request(url: str, data: dict | None = None) -> bytes:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return res.read()


def current_tunnel_url() -> str | None:
    """トンネルが接続済みなら公開 URL を、まだなら None を返す"""
    try:
        # /ready はトンネルの接続が確立するまで 200 以外を返す
        request(f"{CLOUDFLARED_METRICS_URL}/ready")
        hostname = json.loads(request(f"{CLOUDFLARED_METRICS_URL}/quicktunnel")).get("hostname")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return f"https://{hostname}" if hostname else None


def notify(url: str) -> bool:
    message = (
        "📡 SkyMonitor の公開 URL が発行されました\n"
        f"ライブ映像: {url}/\n"
        f"アーカイブ: {url}/gallery.html"
    )
    try:
        request(DISCORD_WEBHOOK_URL, {"content": message})
    except (urllib.error.URLError, OSError) as e:
        log(f"failed to send to Discord: {e}")
        return False
    return True


def main() -> None:
    if not DISCORD_WEBHOOK_URL:
        log("DISCORD_WEBHOOK_URL is not set. notifications are disabled.")

    notified_url = None
    while True:
        url = current_tunnel_url()
        if url and url != notified_url:
            log(f"tunnel url: {url}")
            # 送信に失敗した場合は次の周期で再送する
            if not DISCORD_WEBHOOK_URL or notify(url):
                notified_url = url
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
