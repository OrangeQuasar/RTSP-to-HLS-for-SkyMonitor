# RTSP to HLS for SkyMonitor

同一ネットワーク内の最大4台のカメラから RTSP で映像を受信し、HLS に変換して
Web ページで 2x2 グリッドでリアルタイム視聴できるようにするツールです。

## 構成

```
カメラ1〜4 --RTSP--> streamer1〜4 (ffmpeg) ──HLS────> 共有ボリューム (/hls/cam1〜4/)
                                          └─常時録画─> 共有ボリューム (/recordings/cam1〜4/)
                                                              │
cleanup (定期削除) ──── 保持期間を過ぎた録画を削除 ───────────┘
                                                        │
ブラウザ <--:8000-- web (nginx) ── /          : 静的 HTML (web/index.html, hls.js プレイヤー 2x2)
                                ── /gallery.html : 録画一覧（web/gallery.html）
                                ── /hls/       : HLS セグメント配信
                                ── /recordings/ : 録画クリップの配信
                                ── /api/ ──> api (FastAPI) : ライブ状態・録画一覧を返す
```

- **streamer1〜4**: それぞれ ffmpeg が担当カメラの RTSP を1本受信し、HLS 配信用セグメントと
  常時録画用のクリップ（既定10分単位の mp4、`/recordings/camN` に保存）を同時に書き出す（既定は無変換コピーで低負荷）
- **cleanup**: `RECORDING_RETENTION_DAYS`（既定3日）を過ぎた録画ファイルを1時間おきに走査して削除する
- **web**: nginx がビューアーページ・録画一覧ページ・HLS・録画クリップ・API を同一オリジンの1ポートで配信
- **api**: FastAPI が `/api/status`（カメラごとのライブ状態とラベル）と `/api/recordings`（録画一覧、新しい順・最大300件）を返す（uv で依存管理）。
  ライブページはステータスを 10 秒ごとにポーリングして自動更新する
- **録画一覧**（`/gallery.html`）: `/api/recordings` の一覧をカード表示し、クリックするとクリップ動画を再生する

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

3. ブラウザで `http://<このマシンのIP>:8000` を開く

## 設定 (.env)

| 変数 | 既定値 | 説明 |
|---|---|---|
| `RTSP_URL_1`〜`RTSP_URL_4` | (必須) | 各カメラの RTSP URL。例: `rtsp://user:pass@192.168.1.101:554/stream1` |
| `VIDEO_CODEC_1`〜`VIDEO_CODEC_4` | `copy` | `copy` = 無変換（H.264 カメラ向け）。カメラが H.265 の場合は `h264` にして再エンコード |
| `CAMERA_1_LABEL`〜`CAMERA_4_LABEL` | `カメラ1`〜`カメラ4` | 画面に表示するカメラ名 |
| `RECORDING_RETENTION_DAYS` | `3` | 常時録画の保持期間（日）。これを超えた録画ファイルは `cleanup` サービスが自動削除する |
| `RECORDING_SEGMENT_SECONDS` | `600` | 常時録画のファイル分割間隔（秒）。この単位でアーカイブの1本の映像が区切られる |
| `SAVE_CLIP_SECONDS` | `30` | ライブ画面の「今すぐ保存」でダウンロードできるクリップの長さ（秒） |

公開ポートは `8000` 固定（`docker-compose.yml` の `ports` で指定）。変更したい場合は `docker-compose.yml` を直接編集してください。

## 注意

- HLS の特性上、実映像から数秒程度の遅延があります。
- 映像が出ない場合は `docker compose logs streamer1`（他は `streamer2`〜`4`）で ffmpeg のエラーを確認してください。
  カメラのコーデックが H.265 の場合は該当カメラの `VIDEO_CODEC_N=h264` を試してください。
- 音声は配信しません（`-an`）。
- カメラが4台未満の場合も、使わない `RTSP_URL_N` にダミーの URL を設定しておく必要があります（該当パネルはオフライン表示のままになります）。
- 録画は `/gallery.html` から確認できます。個別に見たい場合は `docker compose exec streamer1 ls /recordings/cam1`
  のように各コンテナ内を直接参照することもできます。
- ライブ画面（`/`）の各カメラパネルにある「今すぐ保存」ボタンを押すと、直近のクリップ（既定30秒、`SAVE_CLIP_SECONDS`
  で変更可能）をその場でブラウザにダウンロードできます。サーバー側の `/recordings` には保存されないため、
  アーカイブには表示されません。
- `RECORDING_RETENTION_DAYS` を超えた録画は `cleanup` サービスが1時間おきに削除します（`cleanup/cleanup.sh` の
  `CLEANUP_INTERVAL_SECONDS` で間隔を変更可能）。

## ローカル開発（Docker なし）

API 単体はローカルでも起動できます。

```bash
uv run uvicorn main:app --reload
# http://localhost:8000/api/status
```

※ ページ（`web/index.html`）は同一オリジンの `/hls/` と `/api/` を前提にしているため、
プレイヤーを含めた動作確認は `docker compose up -d --build` で行ってください。
