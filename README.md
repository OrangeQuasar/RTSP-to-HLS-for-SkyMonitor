# RTSP to HLS for SkyMonitor

同一ネットワーク内の最大4台のカメラから RTSP で映像を受信し、HLS に変換して
Streamlit の Web ページで 2x2 グリッドでリアルタイム視聴できるようにするツールです。

## 構成

```
カメラ1〜4 --RTSP--> streamer1〜4 (ffmpeg) --HLS--> 共有ボリューム (/hls/cam1〜4/)
                                                        ├─ hls-server (nginx) :8888  ← ブラウザが m3u8/ts を取得
                                                        └─ app (Streamlit)    :8501  ← hls.js プレイヤー(2x2)を表示
```

- **streamer1〜4**: それぞれ ffmpeg が担当カメラの RTSP を受信し HLS セグメントに変換（既定は無変換コピーで低負荷）
- **hls-server**: nginx が全カメラの HLS ファイルを CORS 付きで配信
- **app**: Streamlit + hls.js による 2x2 ライブプレイヤー（uv で依存管理）

## 使い方

1. `.env` に4台のカメラの RTSP URL を設定する

   ```bash
   cp .env.example .env
   # RTSP_URL_1〜4 を自分のカメラに書き換える
   ```

2. 起動する

   ```bash
   docker compose up -d --build
   ```

3. ブラウザで `http://<このマシンのIP>:8501` を開く

## 設定 (.env)

| 変数 | 既定値 | 説明 |
|---|---|---|
| `RTSP_URL_1`〜`RTSP_URL_4` | (必須) | 各カメラの RTSP URL。例: `rtsp://user:pass@192.168.1.101:554/stream1` |
| `VIDEO_CODEC_1`〜`VIDEO_CODEC_4` | `copy` | `copy` = 無変換（H.264 カメラ向け）。カメラが H.265 の場合は `h264` にして再エンコード |
| `CAMERA_1_LABEL`〜`CAMERA_4_LABEL` | `カメラ1`〜`カメラ4` | 画面に表示するカメラ名 |
| `HLS_PORT` | `8888` | HLS 配信ポート。視聴するブラウザからアクセスできる必要あり |

## 注意

- HLS の特性上、実映像から数秒程度の遅延があります。
- 映像が出ない場合は `docker compose logs streamer1`（他は `streamer2`〜`4`）で ffmpeg のエラーを確認してください。
  カメラのコーデックが H.265 の場合は該当カメラの `VIDEO_CODEC_N=h264` を試してください。
- 音声は配信しません（`-an`）。
- カメラが4台未満の場合も、使わない `RTSP_URL_N` にダミーの URL を設定しておく必要があります（該当パネルはオフライン表示のままになります）。

## ローカル開発（Docker なし）

```bash
uv run streamlit run main.py
```

※ HLS ストリームは Docker 側のサービスが生成するため、プレイヤーの動作確認には
`docker compose up streamer hls-server` を併用してください。
