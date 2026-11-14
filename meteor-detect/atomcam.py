#!/usr/bin/env python

from pathlib import Path
import sys
import os
from datetime import datetime, timedelta
import time
import argparse
import logging
import numpy as np
import cv2
from imutils.video import FileVideoStream
# telnetlib(時計機能)と yt_dlp(YouTube入力)は使う時だけ import する。

# マルチスレッド関係
import threading
import queue

# 行毎に標準出力のバッファをflushする。
sys.stdout.reconfigure(line_buffering=True)

# 標準出力は検出ログ(atomutil.pyで読む)専用とし、エラー等は標準エラーに出す。
logger = logging.getLogger("atomcam")

# 自分の環境のATOM CamのIPに修正してください(環境変数でも指定可)。
ATOM_CAM_IP = os.environ.get("ATOM_CAM_IP", "192.168.2.110")
ATOM_CAM_RTSP = "rtsp://{}:8554/unicast".format(ATOM_CAM_IP)

# atomcam_toolsでのデフォルトのユーザアカウント(環境変数でも指定可)。
ATOM_CAM_USER = os.environ.get("ATOM_CAM_USER", "root")
ATOM_CAM_PASS = os.environ.get("ATOM_CAM_PASS", "atomcam2")

# YouTube ライブ配信ソース (変更になった場合は要修正)
YouTube = {
    "SDRS6JQulmI": "Kiso",
    "_8rp1p_tWlc": "Subaru",
    "ylSiGa_U1UE": "Fukushima",
    "any_youtube": "YouTube"
}

# タイムスタンプ表示部分のマスク領域(1920x1080基準)。他の解像度ではスケールする。
BASE_WIDTH, BASE_HEIGHT = 1920, 1080
TIMESTAMP_RECT = {
    "ATOMCam": ((1390, 1010), (1920, 1080)),
    "Subaru": ((1660, 980), (1920, 1080)),
}

# FPSが取得できない場合の値(ATOM Cam相当)
DEFAULT_FPS = 15


# ---------------------------------------------------------------------------
# 共通ユーティリティ
# ---------------------------------------------------------------------------

def format_obs_time(t):
    """ログ出力用の時刻文字列 (yyyy/mm/dd HH:MM:SS)"""
    return t.strftime("%Y/%m/%d %H:%M:%S")


def format_file_time(t):
    """ファイル名用の時刻文字列 (yyyymmddHHMMSS)"""
    return t.strftime("%Y%m%d%H%M%S")


def prepare_output_dir(output):
    """出力先ディレクトリを用意する(未指定ならカレントディレクトリ)。"""
    if not output:
        return Path('.')
    output_dir = Path(output)
    output_dir.mkdir(exist_ok=True)
    return output_dir


def to_numpy(img):
    """UMat(OpenCL)の場合はnumpy配列に変換する。"""
    return img.get() if isinstance(img, cv2.UMat) else img


def detect_source(video_url):
    """入力URLからソース名を判定する。"""
    if "youtube" in video_url or "youtu.be" in video_url:
        # YouTube(マウナケア、木曽、福島、etc)
        for key, name in YouTube.items():
            if key in video_url:
                return name
        return "YouTube"
    return "ATOMCam"


def compute_end_time(end_time, now=None):
    """'hhmm' 形式の終了時刻から、次に来るその時刻の datetime を返す。"""
    now = now or datetime.now()
    t = datetime.strptime(end_time, "%H%M")
    end = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    if now > end:
        end += timedelta(hours=24)
    return end


def get_youtube_stream_url(url):
    """YouTubeのURLから OpenCV で開けるストリームURLを取得する(yt-dlp使用)。
    """
    try:
        import yt_dlp
    except ModuleNotFoundError:
        raise SystemExit("YouTube入力には yt-dlp が必要です: pip install yt-dlp")

    opts = {"format": "best[ext=mp4]/best", "quiet": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info["url"]


def make_mask(width, height, source="ATOMCam", mask_path=None, opencl=False):
    """検出対象外の領域を白(255)にしたマスク画像を作成する。

    Args:
      width, height: 入力映像のサイズ
      source: 入力ソース名(タイムスタンプ位置の決定に使う)
      mask_path: マスク画像ファイル(指定時はこちらを優先)
      opencl: UMatで返す場合True

    Returns:
      マスク画像。マスク不要の場合はNone
    """
    if mask_path:
        mask = cv2.imread(mask_path)
        if mask is None:
            raise FileNotFoundError(f"マスク画像を読み込めません: {mask_path}")
        if mask.shape[:2] != (height, width):
            logger.warning("mask size %dx%d -> resized to %dx%d",
                           mask.shape[1], mask.shape[0], width, height)
            mask = cv2.resize(mask, (width, height),
                              interpolation=cv2.INTER_NEAREST)
    else:
        if source == "YouTube":
            # no mask
            return None
        (x0, y0), (x1, y1) = TIMESTAMP_RECT.get(source, TIMESTAMP_RECT["ATOMCam"])
        sx, sy = width / BASE_WIDTH, height / BASE_HEIGHT
        mask = np.zeros((height, width, 3), np.uint8)
        cv2.rectangle(mask, (int(x0 * sx), int(y0 * sy)),
                      (int(x1 * sx), int(y1 * sy)), (255, 255, 255), -1)

    if opencl:
        mask = cv2.UMat(mask)
    return mask


# ---------------------------------------------------------------------------
# ATOM Cam の時計 (telnet, atomcam_tools必要)
# ---------------------------------------------------------------------------

class AtomTelnet():
    '''
    ATOM Camにtelnet接続し、コマンドを実行するクラス
    '''

    def __init__(self, ip_address=ATOM_CAM_IP):
        """AtomTelnetのコンストラクタ

        Args:
          ip_address: Telnet接続先のIPアドレス
        """
        self.tn = None
        try:
            # Python 3.13以降は標準ライブラリから削除されたため standard-telnetlib が必要。
            import telnetlib
        except ModuleNotFoundError:
            raise SystemExit(
                "時計機能には telnetlib が必要です (Python 3.13以降: pip install standard-telnetlib)")
        self.tn = telnetlib.Telnet(ip_address)
        self.tn.read_until(b"login: ")
        self.tn.write(ATOM_CAM_USER.encode('ascii') + b"\n")
        self.tn.read_until(b"Password: ")
        self.tn.write(ATOM_CAM_PASS.encode('ascii') + b"\n")

        self.tn.read_until(b"# ")

    def exec(self, command):
        """Telnet経由でコマンドを実行する。

        Args:
          command : 実行するコマンド(ex. "ls")

        Returns:
          コマンド実行結果文字列。1行のみ。
        """
        self.tn.write(command.encode('utf-8') + b'\n')
        return self.tn.read_until(b"# ").decode('utf-8').split("\r\n")[1]

    def exit(self):
        if self.tn:
            self.tn.write(b"exit\n")
            self.tn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.exit()

    def __del__(self):
        self.exit()


def check_clock():
    """ATOM Camのクロックとホスト側のクロックの比較。
    """
    with AtomTelnet() as tn:
        atom_date = tn.exec('date')
    jst_now = datetime.now()
    atom_now = datetime.strptime(atom_date, "%a %b %d %H:%M:%S %Z %Y")
    delta = (atom_now - jst_now).total_seconds()

    print("# ATOM Cam =", atom_now)
    print("# HOST PC  =", jst_now)
    print("# ATOM Cam - Host PC = {:.3f} sec".format(delta))


def set_clock():
    """ATOM Camのクロックとホスト側のクロックに合わせる。
    """
    with AtomTelnet() as tn:
        jst_now = datetime.now()
        set_command = 'date -s "{}"'.format(jst_now.strftime("%Y-%m-%d %H:%M:%S"))
        print(set_command)
        tn.exec(set_command)


# ---------------------------------------------------------------------------
# 画像処理
# ---------------------------------------------------------------------------

def average(img_list, opencl=False):
    """平均画像"""
    return np.average([to_numpy(img) for img in img_list], axis=0).astype(np.uint8)


def brightest(img_list):
    """比較明合成処理
    Args:
      img_list: 画像データのリスト

    Returns:
      比較明合成された画像
    """
    output = img_list[0]
    for img in img_list[1:]:
        output = cv2.max(img, output)
    return output


def diff(img_list, mask):
    """画像リストから隣接フレーム間の差分画像のリストを作成する。

    Args:
      img_list: 画像データのリスト
      mask: マスク画像(2値画像)。白の部分は差分が0になる。

    Returns:
      差分画像のリスト
    """
    if mask is not None:
        # 各フレームに1回だけマスクをかける。
        img_list = [cv2.bitwise_or(img, mask) for img in img_list]
    return [cv2.subtract(img1, img2)
            for img1, img2 in zip(img_list[:-1], img_list[1:])]


def detect(img, min_length):
    """画像上の線状のパターンを流星として検出する。
    Args:
      img: 検出対象となる画像
      min_length: HoughLinesPで検出する最短長(ピクセル)
    Returns:
      検出結果(検出なしの場合はNone)
    """
    blur = cv2.GaussianBlur(img, (5, 5), 0)
    canny = cv2.Canny(blur, 100, 200, 3)

    # The Hough-transform algo:
    lines = cv2.HoughLinesP(canny, 1, np.pi/180, 25, minLineLength=min_length, maxLineGap=5)
    # OpenCL版はUMatが返り、検出なしでもNoneにならない。
    lines = to_numpy(lines)
    if lines is None or len(lines) == 0:
        return None
    return lines


# ---------------------------------------------------------------------------
# 流星検出
# ---------------------------------------------------------------------------

class MeteorDetector:
    """流星検出の共通処理(ストリーミング版、ファイル版の親クラス)。

    サブクラスは WIDTH, HEIGHT, FPS を設定してから init_detector() を呼ぶ。
    """

    def init_detector(self, source, mask=None, minLineLength=30, opencl=False,
                      output=None):
        self.source = source
        self.opencl = opencl
        self.min_length = minLineLength
        self.output_dir = prepare_output_dir(output)
        # マスク画像指定がなければ時刻表示部分のマスクを作成(入力解像度に合わせる)
        self.mask = make_mask(self.WIDTH, self.HEIGHT, source, mask, opencl)

    def is_meteor(self, img_list):
        """画像リスト中に流星(移動天体)があるか判定する。

        差分間で比較明合成を取るために最低3フレームが必要。
        """
        if len(img_list) < 3:
            return False
        diff_img = brightest(diff(img_list, self.mask))
        return detect(diff_img, self.min_length) is not None

    def save_detection(self, img_list, name, composite_img=None):
        """検出時の比較明合成画像と動画を保存する。

        Args:
          img_list: 画像のリスト
          name: ファイル名(拡張子なし)
          composite_img: 比較明合成画像(計算済みの場合)
        """
        if composite_img is None:
            composite_img = brightest(img_list)
        cv2.imwrite(str(Path(self.output_dir, name + ".jpg")), composite_img)
        self.save_movie(img_list, str(Path(self.output_dir, "movie-" + name + ".mp4")))

    def save_movie(self, img_list, pathname):
        """
        画像リストから動画を作成する。

        Args:
          img_list: 画像のリスト
          pathname: 出力ファイル名
        """
        size = (self.WIDTH, self.HEIGHT)
        fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')

        video = cv2.VideoWriter(pathname, fourcc, self.FPS, size)
        for img in img_list:
            video.write(img)
        video.release()


class AtomCam(MeteorDetector):
    """RTSPストリーミング、YouTube、動画ファイルからのリアルタイム流星検出(スレッド版)
    """

    def __init__(self, video_url=ATOM_CAM_RTSP, output=None, end_time="0600",
                 clock=False, mask=None, minLineLength=30, opencl=False):
        # video device url or movie file path
        self.capture = None
        self.url = video_url
        source = detect_source(video_url)
        self.source = source
        # MP4ファイル再生の場合を区別する。
        self.mp4 = Path(video_url).suffix == '.mp4'

        self.connect()
        if not self.capture.isOpened():
            raise RuntimeError("入力を開けません: {}".format(video_url))
        # opencv-python 4.6.0.66 のバグで大きな値(9000)が返ることがあるので対策。
        self.FPS = min(int(self.capture.get(cv2.CAP_PROP_FPS)), 60)
        if self.FPS < 1:
            self.FPS = DEFAULT_FPS
        self.HEIGHT = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.WIDTH = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))

        # 終了時刻を設定する。
        self.now = datetime.now()
        self.end_time = compute_end_time(end_time, self.now)
        print("# scheduled end_time = ", self.end_time)

        if source == "ATOMCam" and clock:
            # 内蔵時計のチェック
            check_clock()

        self.init_detector(source, mask, minLineLength, opencl, output)

        self.image_queue = queue.Queue(maxsize=200)
        # スレッド間の状態
        self._running = True
        self._producer_done = False

    def __del__(self):
        print("# {} stop".format(format_obs_time(datetime.now())))

        if self.capture:
            self.capture.release()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            # GUI非対応のOpenCV(headless版)の場合
            pass

    def connect(self):
        if self.capture:
            self.capture.release()

        if self.source in YouTube.values():
            # YouTubeからのストリーミング入力
            url = get_youtube_stream_url(self.url)
        else:
            url = self.url

        self.capture = cv2.VideoCapture(url)

    def stop(self):
        # thread を止める
        self._running = False

    def run(self, exposure=1, no_window=False):
        """読み込みスレッドを起動し、終了するまで流星検出を行う。"""
        print("# {} start".format(format_obs_time(datetime.now())))

        t_in = threading.Thread(target=self.queue_streaming)
        t_in.start()
        try:
            self.dequeue_streaming(exposure, no_window)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
            t_in.join()

    # --- 読み込み側(スレッド) ---

    def _put(self, item):
        """queueへの書き込み。停止要求があれば諦めてFalseを返す(デッドロック防止)。
        """
        while self._running:
            try:
                self.image_queue.put(item, timeout=0.5)
                return True
            except queue.Full:
                continue
        return False

    def queue_streaming(self):
        """RTSP読み込みをthreadで行い、queueにデータを流し込む。
        """
        print("# threading version started.")
        try:
            while self._running:
                try:
                    ret, frame = self.capture.read()
                    if not ret:
                        if self.mp4:
                            # 動画ファイルの終端
                            break
                        # ストリーミングが切れた場合は再接続する。
                        logger.warning("stream lost, reconnecting: %s", self.url)
                        self.connect()
                        time.sleep(5)
                        continue

                    if self.opencl:
                        frame = cv2.UMat(frame)
                    if not self._put((datetime.now(), frame)):
                        break
                except Exception:
                    logger.exception("frame read error")
                    # 例外が続く場合に CPU を使い切らないようにする。
                    time.sleep(0.1)
        finally:
            self._producer_done = True

    # --- 検出側(メインスレッド) ---

    def _get(self):
        """queueからの読み出し。読み込みスレッドが終了し、queueが空ならNoneを返す。
        """
        while True:
            try:
                return self.image_queue.get(timeout=0.5)
            except queue.Empty:
                if self._producer_done and self.image_queue.empty():
                    return None
                if not self._running:
                    return None

    def _frame_chunks(self, exposure, no_window):
        """queueのフレームを exposure 秒ごとに区切って (先頭時刻, 画像リスト) を返す。

        入力の終わり、または 'q' キーで終了する。
        """
        num_frames = int(self.FPS * exposure)
        # exposure time を超えたフレームは次の区間の先頭に回す。
        pending = None

        while True:
            img_list = []
            t0 = None
            while len(img_list) < num_frames:
                item = pending if pending is not None else self._get()
                pending = None
                if item is None:
                    # 入力の終わり(動画ファイルの終端など)
                    if img_list:
                        yield t0, img_list
                    return

                (t, frame) = item
                if t0 is None:
                    t0 = t
                elif (t - t0).total_seconds() >= exposure:
                    # exposure time を超えたら区間を区切る
                    pending = item
                    break
                img_list.append(frame)

                if not no_window and chr(cv2.waitKey(1) & 0xFF) == 'q':
                    return

            yield t0, img_list

    def dequeue_streaming(self, exposure=1, no_window=False):
        """queueからデータを読み出し流星検知、描画を行う。
        """
        try:
            for t0, img_list in self._frame_chunks(exposure, no_window):
                if len(img_list) > 2:
                    composite_img = brightest(img_list)
                    if not no_window:
                        cv2.imshow(self.source, composite_img)
                    self.detect_meteor(img_list, t0, composite_img)

                # ストリーミングの場合、終了時刻を過ぎたなら終了。
                now = datetime.now()
                if not self.mp4 and now > self.end_time:
                    print("# end of observation at ", now)
                    return
        finally:
            # 読み込みスレッドも止める
            self._running = False

    def detect_meteor(self, img_list, t0=None, composite_img=None):
        """img_listで与えられた画像のリストから流星(移動天体)を検出する。

        Args:
          img_list: 画像のリスト
          t0: 先頭フレームの取得時刻(検出時刻として使う)
          composite_img: 比較明合成画像(計算済みの場合)
        """
        if len(img_list) < 3:
            return
        now = t0 if t0 is not None else datetime.now()

        try:
            if now.hour != self.now.hour:
                # 毎時空の様子を記録する。
                path_name = Path(self.output_dir, "sky-" + format_file_time(now) + ".jpg")
                cv2.imwrite(str(path_name), average(img_list, self.opencl))
                self.now = now

            if self.is_meteor(img_list):
                print('{} A possible meteor was detected.'.format(format_obs_time(now)))
                self.save_detection(img_list, format_file_time(now), composite_img)
        except Exception:
            logger.exception("meteor detection error")


class DetectMeteor(MeteorDetector):
    """
    ATOMCam 動画ファイル(MP4)からの流星の検出
    """

    def __init__(self, file_path, mask=None, minLineLength=30, opencl=False):
        self.capture = FileVideoStream(file_path).start()
        self.HEIGHT = int(self.capture.stream.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.WIDTH = int(self.capture.stream.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.FPS = self.capture.stream.get(cv2.CAP_PROP_FPS)
        if self.FPS < 1.0:
            # 正しく入っていない場合があるので、その場合は15固定にする(ATOM Cam限定)。
            self.FPS = DEFAULT_FPS

        # file_path (.../yyyymmdd/hh/mm.mp4) から日付、時刻を取得する。
        path = Path(file_path)
        self.date_dir = path.parent.parent.name
        self.hour = path.parent.name
        self.minute = path.stem
        date = datetime.strptime(self.date_dir, "%Y%m%d")
        self.obs_time = "{} {}:{}".format(date.strftime("%Y/%m/%d"), self.hour, self.minute)

        # ATOM Cam形式のファイル専用なので、ATOM Camのタイムスタンプをマスクする。
        self.init_detector("ATOMCam", mask, minLineLength, opencl)

    def _frame_chunks(self, num_frames):
        """動画を num_frames ごとに区切った画像リストを返す。"""
        while self.capture.more():
            img_list = []
            while len(img_list) < num_frames and self.capture.more():
                frame = self.capture.read()
                if frame is None:
                    continue
                if self.opencl:
                    frame = cv2.UMat(frame)
                img_list.append(frame)
            yield img_list

    def meteor(self, exposure=1, output=None):
        """流星の検出
        """
        self.output_dir = prepare_output_dir(output)
        num_frames = int(self.FPS * exposure)

        for count, img_list in enumerate(self._frame_chunks(num_frames)):
            # この区間の先頭の秒(0, exposure, 2*exposure, ...)
            second = str(count * exposure).zfill(2)
            try:
                if self.is_meteor(img_list):
                    print('{}:{}  A possible meteor was detected.'.format(self.obs_time, second))
                    name = self.date_dir + self.hour + self.minute + second
                    self.save_detection(img_list, name)
            except Exception:
                logger.exception("meteor detection error")


# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------

def detect_meteor(args):
    """
    ATOM Cam形式の動画ファイルからの流星の検出
    """
    # 入力ファイルのディレクトリの指定がなければカレントディレクトリ
    data_dir = Path(args.input or '.', args.date)
    if args.hour:
        # 時刻(hour)の指定がある場合
        data_dir = Path(data_dir, args.hour)

    print("# {}".format(data_dir))

    if args.hour and args.minute:
        # 1分間の単体のmp4ファイルの処理
        file_paths = [Path(data_dir, "{}.mp4".format(args.minute))]
    else:
        # 1時間内の一括処理
        file_paths = sorted(data_dir.glob("[0-9][0-9].mp4"))

    for file_path in file_paths:
        print("#", file_path)
        detecter = DetectMeteor(
            str(file_path), mask=args.mask, minLineLength=args.min_length,
            opencl=args.opencl)
        detecter.meteor(args.exposure, args.output)


def streaming_thread(args):
    """
    RTSPストリーミング、及び動画ファイルからの流星の検出(スレッド版)
    """
    if args.url:
        # URL指定の場合。
        url = args.url
    elif args.atomcam_tools:
        # atomcam_toolsのRTSPを使う場合。
        url = ATOM_CAM_RTSP
    else:
        # メーカ公式のRTSPを使う場合
        url = f"rtsp://6199:4003@{ATOM_CAM_IP}/live"

    try:
        atom = AtomCam(url, args.output, args.to, args.clock,
                       args.mask, args.min_length, args.opencl)
    except (RuntimeError, FileNotFoundError) as e:
        logger.error("%s", e)
        return

    atom.run(args.exposure, args.no_window)


def build_parser():
    parser = argparse.ArgumentParser(add_help=False)

    # ストリーミングモードのオプション
    parser.add_argument('-u', '--url', default=None,
                        help='RTSPのURL、または動画(MP4)ファイル')
    parser.add_argument('-n', '--no_window', action='store_true', help='画面非表示')

    # 以下はATOM Cam形式のディレクトリからデータを読む場合のオプション
    parser.add_argument('-d', '--date', default=None,
                        help="Date in 'yyyymmdd' format (JST)")
    parser.add_argument('-h', '--hour', default=None,
                        help="Hour in 'hh' format (JST)")
    parser.add_argument('-m', '--minute', default=None,
                        help="minute in mm (optional)")
    parser.add_argument('-i', '--input', default=None, help='検出対象のTOPディレクトリ名')

    # 共通オプション
    parser.add_argument('-e', '--exposure', type=int,
                        default=1, help='露出時間(second)')
    parser.add_argument('-o', '--output', default=None, help='検出画像の出力先ディレクトリ名')
    parser.add_argument('-t', '--to', default="0600",
                        help='終了時刻(JST) "hhmm" 形式(ex. 0600)')

    parser.add_argument('--mask', default=None, help="mask image")
    parser.add_argument('--min_length', type=int, default=30,
                        help="minLineLength of HoghLinesP")

    parser.add_argument('--opencl',
                        action='store_true', help="Use OpenCL (default: False)")

    # ffmpeg関係の警告がウザいので抑制する。
    parser.add_argument('-s', '--suppress-warning',
                        action='store_true', help='suppress warning messages')

    # threadモード(default)。前のバージョンとの互換のため形だけ残している。
    parser.add_argument('--thread', default=True,
                        action='store_true', help='スレッド版(default)')

    parser.add_argument('--help', action='help',
                        help='show this help message and exit')

    # 以下のオプションはatomcam_toolsを必要とする。
    parser.add_argument(
        '--atomcam_tools', action='store_true', help='atomcam_toolsを使う場合に指定する。')
    parser.add_argument(
        '-c', '--clock', action='store_true', help='カメラの時刻チェック(atomcam_tools必要)')

    return parser


def main():
    args = build_parser().parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="# %(levelname)s: %(message)s")

    if args.suppress_warning:
        # stderrを dev/null に出力する。
        fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(fd, 2)

    if args.date:
        # 日付がある場合はファイル(ATOMCam形式のファイル)から流星検出
        detect_meteor(args)
    else:
        # ストリーミング/動画(MP4)の再生、流星検出
        streaming_thread(args)


if __name__ == '__main__':
    main()
