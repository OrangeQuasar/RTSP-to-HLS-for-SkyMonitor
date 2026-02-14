# SkyMonitor

RTSP カメラを HLS に変換し、4 画面ダッシュボードで表示する FastAPI アプリです。
管理画面からカメラ名と RTSP URL を設定できます。

## できること

- 4 台の RTSP 映像を 2x2 で同時表示
- 管理画面でカメラ名/RTSP を変更して即反映
- HLS 配信によりブラウザで再生可能
- Docker + Nginx 構成に対応

## 必要要件（ローカル）

- Python 3.10+
- FFmpeg（PATH に通っていること）
- uv（https://github.com/astral-sh/uv）

## ローカル開発（uv）

```
uv venv
\.venv\Scripts\Activate.ps1
uv sync
```

起動:

```
uvicorn app.main:app --reload
```

アクセス:

- http://127.0.0.1:8000/ （ビューア）
- http://127.0.0.1:8000/admin （管理画面）

## Docker Compose で起動

```
docker compose up --build
```

アクセス:

- http://localhost:8000/ （アプリ直アクセス）
- http://localhost/ （Nginx 経由）

## Localtunnel での公開

ローカルネットワークの外部に公開したい場合は **localtunnel** を使用できます。

### インストール（ホストマシン）

```
npm install -g localtunnel
```

### 公開方法

**方法1: Nginx 経由での公開（推奨）**

```bash
# ホストマシンでコマンドを実行
lt --port 80
```

出力例:

```
your url is: https://your-subdomain.loca.lt
```

その URL にアクセスするとアプリが利用できます。

**方法2: FastAPI 直接公開**

```bash
# ホストマシンでコマンドを実行
lt --port 8000
```

### セキュリティ上の注意

- Localtunnel URL は不特定多数にアクセス可能です
- 管理画面へのパスワード保護を必ず有効化してください
- 本番環境では HTTPS（TLS）の設定を必ず行ってください

## Nginx 直配信について

Nginx は以下を直配信しています。

- /static/ （CSS/JS）
- /hls/ （HLS の m3u8/ts）

メリット:

- ファイル配信の高速化
- アプリ負荷の低減
- キャッシュ制御の自由度向上

設定は [nginx/nginx.conf](nginx/nginx.conf) を参照してください。

## 設定ファイル

設定は [config.json](config.json) に保存されます。

例:

```
{
	"admin_password": "admin",
	"layout": "2x2",
	"hls_root": "hls",
	"cameras": [
		{
			"id": "cam1",
			"name": "Camera 1",
			"rtsp_url": "rtsp://user:pass@host/stream1",
			"enabled": true,
			"width": 1280,
			"height": 720,
			"fps": 15
		}
	]
}
```

## 管理画面

- URL: /admin
- 初回パスワードは config.json の admin_password
- カメラ名と RTSP を変更して保存すると、FFmpeg を再起動して反映します

## HLS の安定再生のための設定

HLS のセグメントが数秒で止まる場合に備え、FFmpeg は以下の設定で起動しています。

- GOP を 2 秒で固定
- 独立セグメント化
- プレイリスト長を 6 に拡大

設定は [app/rtsp.py](app/rtsp.py) にあります。

## よくあるトラブル

### 映像が数秒で止まる

- RTSP 側のキーフレームが遅い場合に発生します
- HLS の GOP/リスト設定を見直してください

### Docker で起動できない

- Docker Desktop が起動しているか確認
- 依存解決に失敗する場合はビルドログを確認

### Nginx 経由で再生できない

- /hls/ が Nginx にマウントされているか確認
- Nginx のエラーログを確認

## 依存更新

pyproject.toml を変更した場合:

```
uv lock
```

## セキュリティの注意

- 管理画面のパスワードは必ず変更
- 公開時は Nginx で TLS を有効化することを推奨
- 設定ファイルに含まれる RTSP 認証情報の取り扱いに注意
