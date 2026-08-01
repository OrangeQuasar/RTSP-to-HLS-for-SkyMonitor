# RTSP to HLS for SkyMonitor

同一ネットワーク内の最大4台のカメラから RTSP で映像を受信し、HLS に変換して
Web ページで 2x2 グリッドでリアルタイム視聴できるようにするツールです。

## 構成

```
カメラ1〜4 --RTSP--> streamer1〜4 (ffmpeg) --HLS--> 共有ボリューム (/hls/cam1〜4/)
                                                        │
ブラウザ <--:8000-- web (nginx) ── /          : 静的 HTML (web/index.html, hls.js プレイヤー 2x2)
                                ── /hls/      : HLS セグメント配信
                                ── /api/ ──> api (FastAPI) : カメラのライブ状態を返す
```

- **streamer1〜4**: それぞれ ffmpeg が担当カメラの RTSP を受信し HLS セグメントに変換（既定は無変換コピーで低負荷）
- **web**: nginx がビューアーページ・HLS・API を同一オリジンの1ポートで配信
- **api**: FastAPI が `/api/status` でカメラごとのライブ状態とラベルを返す（uv で依存管理）。
  ページはこれを 10 秒ごとにポーリングしてステータス表示を自動更新する
- **detector2**（テスト導入）: [meteor-detect](https://github.com/kin-hasegawa/meteor-detect) がカメラ2の RTSP を直接監視し、
  流星・火球らしき動きを検出したら合成画像・クリップ動画・1時間ごとの空全体画像を `/recordings/cam2` に書き出す
- **検出ギャラリー**（`/gallery.html`）: `api` が `/api/recordings` で検出イベント一覧（新しい順、最大300件）を返し、
  ページはサムネイル画像をクリックするとクリップ動画を再生する

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

公開ポートは `8000` 固定（`docker-compose.yml` の `ports` で指定）。変更したい場合は `docker-compose.yml` を直接編集してください。

## 注意

- HLS の特性上、実映像から数秒程度の遅延があります。
- 映像が出ない場合は `docker compose logs streamer1`（他は `streamer2`〜`4`）で ffmpeg のエラーを確認してください。
  カメラのコーデックが H.265 の場合は該当カメラの `VIDEO_CODEC_N=h264` を試してください。
- 音声は配信しません（`-an`）。
- カメラが4台未満の場合も、使わない `RTSP_URL_N` にダミーの URL を設定しておく必要があります（該当パネルはオフライン表示のままになります）。
- `detector2` の検出結果は `docker compose exec detector2 ls /recordings/cam2` や、Docker のボリューム
  （`recordings`）を直接参照して確認してください。まだ閲覧用ページには繋がっていません。
- meteor-detect は ATOM Cam を主な対象に作られたツールのため、日没〜日の出のスケジューリング（既定で午前6時に終了）など
  一部の挙動が想定と異なる場合があります。誤検出（飛行機・虫など）が多い場合は `--mask` でカメラ視野の不要領域を除外できます。

## ローカル開発（Docker なし）

API 単体はローカルでも起動できます。

```bash
uv run uvicorn main:app --reload
# http://localhost:8000/api/status
```

※ ページ（`web/index.html`）は同一オリジンの `/hls/` と `/api/` を前提にしているため、
プレイヤーを含めた動作確認は `docker compose up -d --build` で行ってください。
