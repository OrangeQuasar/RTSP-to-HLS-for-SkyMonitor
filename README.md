# RTSP to HLS for SkyMonitor

同一ネットワーク内のカメラから RTSP で映像を受信し、ffmpeg で HLS に変換して
Streamlit の Web ページでリアルタイム視聴するアプリです。

## 仕組み

```
[カメラ] --RTSP--> [ffmpeg] --HLS(.m3u8/.ts)--> ./static/hls/
                                                    |
[ブラウザ] <--HTTP(8501)-- [Streamlit + hls.js プレイヤー]
```

- Streamlit アプリが起動時に ffmpeg を子プロセスとして立ち上げ、RTSP を HLS に変換します
- HLS セグメントは Streamlit の静的ファイル配信(`/app/static/hls/`)で配信されます
- ページ側は hls.js で再生します(Safari はネイティブ再生)

## 使い方

1. `.env` を作成してカメラの RTSP URL を設定:

   ```bash
   cp .env.example .env
   # RTSP_URL を自分のカメラに合わせて編集
   ```

2. 起動:

   ```bash
   docker compose up -d --build
   ```

3. ブラウザで <http://localhost:8501> を開く(同一 LAN の他端末からは `http://<ホストのIP>:8501`)

## 設定(環境変数)

| 変数 | 既定値 | 説明 |
| --- | --- | --- |
| `RTSP_URL` | (必須) | カメラの RTSP URL |
| `RTSP_TRANSPORT` | `tcp` | RTSP の転送方式(`tcp` / `udp`) |
| `VIDEO_CODEC` | `copy` | `copy` は無変換(H.264 カメラ向け・低負荷)。映像が出ない H.265 カメラ等は `libx264` |

## トラブルシューティング

- **映像が出ない**: `docker compose logs -f` で ffmpeg のエラーを確認。カメラが H.265 の場合は `.env` に `VIDEO_CODEC=libx264` を設定
- **接続できない**: `ffprobe <RTSP_URL>` などで URL 自体が正しいか確認
- **遅延**: HLS の特性上、数秒程度の遅延があります

## ローカル開発(Docker なし)

ffmpeg がインストールされている環境で:

```bash
RTSP_URL=rtsp://... uv run streamlit run main.py
```
