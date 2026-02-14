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
- FFmpeg
- uv（https://github.com/astral-sh/uv）

### FFmpeg のインストール

**Ubuntu/Debian:**
```bash
sudo apt-get install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
https://ffmpeg.org/download.html からダウンロードして PATH に追加

## ローカル開発（uv）

```bash
# 仮想環境の作成
uv venv

# 仮想環境の有効化
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# 依存パッケージのインストール
uv sync
```

起動:

```bash
uvicorn app.main:app --reload
```

アクセス:

- http://127.0.0.1:8000/ （ビューア）
- http://127.0.0.1:8000/admin （管理画面）

## Docker Compose で起動

```bash
docker compose up --build
```

構成:

- **FastAPI アプリ**: ポート 8000 （Docker 内部）
- **Nginx**: ポート 80 （ホストマシン）
  - / → FastAPI にプロキシ
  - /static/ → 直配信（CSS/JS）
  - /hls/ → 直配信（HLS セグメント）

アクセス:

- http://localhost/ （推奨 - Nginx 経由）
- http://localhost:8000/ （直接アクセス）
  
admin_password は config.json で変更できます。

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
		**URL**: http://localhost/admin
- **初回パスワード**: `admin`（config.json の `admin_password` で変更）
- カメラ名と RTSP を変更して保存すると、FFmpeg を再起動して反映します
- 最大 4 台のカメラに対応（2x2 レイアウト）
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

### 映像が更新されない（プレイリストが304エラー）

- Nginx キャッシュ設定の問題です
- 以下を確認してください：
  - Nginx の ETag を無効化（`etag off;`）
  - m3u8 ファイルで `no-cache, no-store, must-revalidate` を設定
  - Last-Modified ヘッダーを無効化（`add_header Last-Modified "";`）
- ブラウザキャッシュをクリアして再度アクセス

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

- **管理画面のパスワード**: 必ず `config.json` の `admin_password` を変更してください
- **公開時の TLS**: Nginx で HTTPS/TLS を有効化してください
- **RTSP 認証情報**: `config.json` に含まれるため、安全に管理してください
