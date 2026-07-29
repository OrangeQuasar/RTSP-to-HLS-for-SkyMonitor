# RTSP to HLS for SkyMonitor

同一ネットワーク内のカメラから RTSP で映像を受信し、HLS に変換して
Streamlit の Web ページでリアルタイム視聴できるようにするツールです。

## 構成

```
カメラ --RTSP--> streamer (ffmpeg) --HLS--> 共有ボリューム
                                              ├─ hls-server (nginx) :8888  ← ブラウザが m3u8/ts を取得
                                              └─ app (Streamlit)    :8501  ← hls.js プレイヤーを表示
```

- **streamer**: ffmpeg が RTSP を受信し HLS セグメントに変換（既定は無変換コピーで低負荷）
- **hls-server**: nginx が HLS ファイルを CORS 付きで配信
- **app**: Streamlit + hls.js によるライブプレイヤー（uv で依存管理）

## 使い方

1. `.env` にカメラの RTSP URL を設定する

   ```bash
   cp .env.example .env
   # RTSP_URL を自分のカメラに書き換える
   ```

2. 起動する

   ```bash
   docker compose up -d --build
   ```

3. ブラウザで `http://<このマシンのIP>:8501` を開く

## 設定 (.env)

| 変数 | 既定値 | 説明 |
|---|---|---|
| `RTSP_URL` | (必須) | カメラの RTSP URL。例: `rtsp://user:pass@192.168.1.100:554/stream1` |
| `VIDEO_CODEC` | `copy` | `copy` = 無変換（H.264 カメラ向け）。カメラが H.265 の場合は `h264` にして再エンコード |
| `HLS_PORT` | `8888` | HLS 配信ポート。視聴するブラウザからアクセスできる必要あり |

## 注意

- HLS の特性上、実映像から数秒程度の遅延があります。
- 映像が出ない場合は `docker compose logs streamer` で ffmpeg のエラーを確認してください。
  カメラのコーデックが H.265 の場合は `VIDEO_CODEC=h264` を試してください。
- 音声は配信しません（`-an`）。

## ローカル開発（Docker なし）

```bash
uv run streamlit run main.py
```

※ HLS ストリームは Docker 側のサービスが生成するため、プレイヤーの動作確認には
`docker compose up streamer hls-server` を併用してください。
