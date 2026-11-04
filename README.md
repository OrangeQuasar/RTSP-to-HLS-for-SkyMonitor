# RTSP to HLS for SkyMonitor

同一ネットワーク内の最大4台のカメラから RTSP で映像を受信し、HLS に変換して
Web ブラウザで 2x2 グリッドのリアルタイム視聴ができるようにするツールです。
映像は常時（または夜間のみ）録画され、アーカイブ画面からさかのぼって再生できます。

## 主な機能

- **ライブ視聴**（`/`）: 4台のカメラ映像を 2x2 で同時表示。各カメラの受信状態を 10 秒ごとに更新
- **今すぐ保存**: ライブ画面のボタンから、直近のクリップ（既定30秒）を mp4 でダウンロード
- **アーカイブ**（`/gallery.html`）: 録画を日付・時間帯ごとに一覧表示し、クリックで再生（日本時間表示）
- **常時録画・夜間のみ録画**: 既定10分ごとの mp4 として保存。指定した時間帯だけ録画することも可能
- **古い録画の自動削除**: 保持期間（既定3日）を過ぎた録画を自動で削除
- **インターネット公開**（任意）: Cloudflare Quick Tunnel で、アカウント・ポート開放なしで公開
- **Discord 通知**（任意）: 公開 URL が発行されるたびに Discord のチャンネルへ投稿

## 構成

```
カメラ1〜4 --RTSP--> streamer1〜4 (ffmpeg) ──HLS────> 共有ボリューム hls (/hls/cam1〜4/)
                                          └─録画───> 共有ボリューム recordings (/recordings/cam1〜4/)
                                                              │
cleanup ──── 保持期間を過ぎた録画を削除 ───────────────────────┘

インターネット ──> Cloudflare ──Quick Tunnel──> cloudflared ──┐ (任意)
                                                  │           ▼
                         Discord <── notifier <───┘  ブラウザ(LAN) <--:8000-- api (FastAPI)
                                (URL を通知・任意)               ── /               : ライブ画面
                                                                 ── /gallery.html   : アーカイブ
                                                                 ── /hls/           : HLS 配信
                                                                 ── /recordings/    : 録画の配信
                                                                 ── /api/           : API
```

| サービス | 役割 |
|---|---|
| `streamer1`〜`streamer4` | カメラ1台ごとに ffmpeg で RTSP を受信し、ライブ配信用の HLS と録画用の mp4 を書き出す。ffmpeg が落ちても自動で再起動する |
| `cleanup` | 保持期間を過ぎた録画ファイルを定期的に削除する |
| `api` | FastAPI（uvicorn）。ページ・HLS・録画・API をすべてポート 8000 で配信し、「今すぐ保存」の処理と回数制限も行う |
| `cloudflared`（任意） | Cloudflare Quick Tunnel で `api` をインターネットに公開する |
| `notifier`（任意） | `cloudflared` が発行した URL を Discord に通知する |

### ディレクトリ構成

```
.
├── docker-compose.yml   全サービスの定義
├── Dockerfile           api / notifier のイメージ（Python + ffmpeg）
├── main.py              api（FastAPI）
├── notify_discord.py    notifier
├── pyproject.toml, uv.lock  Python の依存関係（uv で管理）
├── streamer/            streamer のイメージ（stream.sh: 受信・HLS 変換・録画）
├── cleanup/             cleanup のイメージ（cleanup.sh: 古い録画の削除）
├── web/                 ブラウザに配信するページ（index.html, gallery.html, style.css）
└── .env.example         設定ファイルのひな形
```

## 使い方

前提: Docker と Docker Compose が使えるマシン（カメラと同じネットワーク内）。

1. 設定ファイルを作り、4台のカメラの RTSP URL を書き換える

   ```bash
   cp .env.example .env
   # RTSP_URL_1〜4 を自分のカメラに書き換える
   ```

2. 起動する

   ```bash
   docker compose up -d --build
   ```

3. ブラウザで `http://<このマシンのIP>:8000` を開く

停止は `docker compose down` です（録画はボリュームに残ります）。

### 設定やコードを変更したとき

| 変更したもの | 反映方法 |
|---|---|
| `.env` | `docker compose up -d`（変更のあったサービスが作り直される） |
| `web/` 内のファイル | ブラウザを再読み込みするだけ（マウントしているため再起動不要） |
| `main.py` / `notify_discord.py` / `streamer/` / `cleanup/` | `docker compose up -d --build` |

## 設定 (.env)

### カメラ

| 変数 | 既定値 | 説明 |
|---|---|---|
| `RTSP_URL_1`〜`RTSP_URL_4` | (必須) | 各カメラの RTSP URL。例: `rtsp://user:pass@192.168.1.101:554/stream1` |
| `VIDEO_CODEC_1`〜`VIDEO_CODEC_4` | `copy` | `copy` = 無変換（H.264 カメラ向け・低負荷）。カメラが H.265 の場合は `h264` にして再エンコード |
| `CAMERA_1_LABEL`〜`CAMERA_4_LABEL` | `カメラ1`〜`カメラ4` | 画面に表示するカメラ名 |

### 録画

| 変数 | 既定値 | 説明 |
|---|---|---|
| `RECORDING_SEGMENT_SECONDS` | `600` | 録画ファイルの分割間隔（秒）。アーカイブの1本の長さになる |
| `RECORDING_RETENTION_DAYS` | `3` | 録画の保持期間（日）。超えたファイルは `cleanup` が削除する |
| `CLEANUP_INTERVAL_SECONDS` | `3600` | 古い録画を削除する処理の実行間隔（秒） |
| `RECORDING_NIGHT_ONLY` | `false` | `true` にすると指定した時間帯のみ録画する。ライブ配信は時間帯に関わらず常時視聴できる |
| `RECORDING_START_HOUR` | `18` | 録画を開始する時刻（0-23、`RECORDING_NIGHT_ONLY=true` のときのみ有効） |
| `RECORDING_END_HOUR` | `6` | 録画を終了する時刻（0-23）。開始時刻より小さい場合は日をまたぐ（既定は18時〜翌6時） |
| `RECORDING_HOURS_TZ` | `JST-9` | 開始・終了時刻を判定するタイムゾーン（POSIX 形式）。録画ファイル名は UTC のまま |

### 今すぐ保存

| 変数 | 既定値 | 説明 |
|---|---|---|
| `SAVE_CLIP_SECONDS` | `30` | ダウンロードできるクリップの長さ（秒） |
| `SAVE_RATE_PER_MINUTE` | `6` | 1人の閲覧者が使える平均回数（回/分） |
| `SAVE_BURST` | `4` | 短時間に連続で使える回数 |

### インターネット公開

| 変数 | 既定値 | 説明 |
|---|---|---|
| `COMPOSE_PROFILES` | (なし) | `tunnel` にすると `cloudflared` と `notifier` も起動する |
| `DISCORD_WEBHOOK_URL` | (なし) | 公開 URL を通知する Discord チャンネルの Webhook URL。未設定なら通知しない |

公開ポートは `8000` 固定です（`docker-compose.yml` の `ports` で指定）。変更したい場合は `docker-compose.yml` を直接編集してください。

## インターネットに公開する（Cloudflare Quick Tunnel）

Cloudflare のアカウント・ドメイン・ルーターのポート開放なしで、インターネットから視聴できるようにします。

1. `.env` に `COMPOSE_PROFILES=tunnel` を追加する
2. `docker compose up -d --build` で起動する
3. 発行された URL（`https://xxxx.trycloudflare.com`）を確認する

   ```bash
   docker compose logs cloudflared | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com'
   ```

注意:

- URL は `cloudflared` を再起動するたびに変わります。固定の URL が必要な場合は、Cloudflare アカウントで名前付きトンネルを作成してください。
- Quick Tunnel は Cloudflare が検証・開発用に提供している無料機能で、稼働保証はありません。
- 本システムには認証機能がありません。URL を知っていれば誰でも視聴できます。
- 録画（`/recordings/*.mp4`）はファイルサイズが大きいため、閲覧者が多いと回線帯域を消費します。

### 発行された URL を Discord に通知する

1. Discord で通知したいサーバーのチャンネルを開き、**チャンネルの編集 → 連携サービス → ウェブフック → 新しいウェブフック**
   を作成して **ウェブフック URL をコピー** する（チャンネルの管理権限が必要）
2. `.env` に設定する

   ```bash
   COMPOSE_PROFILES=tunnel
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
   ```

3. `docker compose up -d --build` で起動すると、URL が発行された時点でチャンネルにライブ画面とアーカイブのリンクが投稿される

- `cloudflared` の再起動などで URL が変わった場合も、そのたびに新しい URL が投稿されます
  （`notifier` 自体を再起動した場合も、現在の URL をもう一度投稿します）。
- 送信状況は `docker compose logs notifier` で確認できます。送信に失敗した場合は 10 秒ごとに再送します。
- Webhook URL を知っていれば誰でもそのチャンネルに投稿できてしまうため、`.env` を他人に共有しないでください。

## API

| メソッド・パス | 説明 |
|---|---|
| `GET /api/status` | 各カメラの `id`・表示名 `label`・ライブ状態 `live`（HLS の更新が 30 秒以内なら `true`） |
| `GET /api/recordings` | 録画一覧（新しい順・最大300件）。各要素は `camera_id`・`timestamp`（開始時刻 UTC `YYYYMMDDHHMMSS`）・`end_epoch`（終了時刻の目安）・`video`（ファイル名）。録画中の最新ファイルは含まない |
| `POST /api/recordings/save?camera_id=camN` | 直近 `SAVE_CLIP_SECONDS` 秒のクリップを mp4 で返す（サーバーには保存しない）。`seconds` で短くすることも可能（最短5秒） |
| `GET /healthz` | 死活監視用（`ok` を返す） |

「今すぐ保存」はリクエストごとに ffmpeg を起動するため、閲覧者ごとに回数を制限しています。超えると `429` と
`Retry-After`（再試行までの秒数）を返します。Tunnel 経由のアクセスは、接続元が `cloudflared` コンテナのときに限り
`CF-Connecting-IP` ヘッダーで閲覧者を区別します（LAN から直接アクセスした場合はこのヘッダーを無視します）。
回数の記録はメモリ上にあるため、`api` を再起動するとリセットされます。

## 運用・トラブルシューティング

- **映像が出ない**: `docker compose logs streamer1`（他は `streamer2`〜`4`）で ffmpeg のエラーを確認してください。
  カメラのコーデックが H.265 の場合は該当カメラの `VIDEO_CODEC_N=h264` を試してください。
- **カメラが4台未満**: 使わない `RTSP_URL_N` にもダミーの URL を設定してください（該当パネルはオフライン表示のままになります）。
- **録画ファイルを直接見たい**: `docker compose exec streamer1 ls /recordings/cam1` のように各コンテナ内を参照できます。
  ファイル名は録画開始時刻（UTC）です。
- **アーカイブに最新の録画が出ない**: 録画中のファイルは確定するまで（最大 `RECORDING_SEGMENT_SECONDS` 秒）一覧に出ません。
- **今すぐ保存したクリップ**: ブラウザにダウンロードされるだけで、サーバーには残らずアーカイブにも表示されません。

## 制約

- HLS の特性上、実映像から数秒程度の遅延があります。
- 音声は配信・録画しません。
- カメラ台数は4台固定です（`cam1`〜`cam4`）。
- ライブ配信と録画で別々に RTSP 接続するため、カメラ1台あたり最大2接続になります。

## ローカル開発（Docker なし）

FastAPI 単体はローカルでも起動できます（ページは `web/` から配信されます）。

```bash
HLS_ROOT=./tmp/hls RECORDINGS_ROOT=./tmp/recordings uv run uvicorn main:app --reload
# http://localhost:8000/ , http://localhost:8000/api/status
```

※ 映像は streamer が書き出す HLS が必要なため、プレイヤーを含めた動作確認は `docker compose up -d --build` で行ってください。
