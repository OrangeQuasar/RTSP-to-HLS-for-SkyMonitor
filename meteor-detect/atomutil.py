#!/usr/bin/env python

from pathlib import Path
import argparse
import cv2

from atomcam import DetectMeteor, ATOM_CAM_IP, ATOM_CAM_USER, ATOM_CAM_PASS
from atomcam import check_clock, set_clock


def iter_detections(meteor_list):
    '''
    検出ログ(atomcam.pyの出力)から検出時刻を読み出す。

    Yields:
      (date_dir, hh, mm, ss): date_dir は 'yyyymmdd' 形式
    '''
    with open(meteor_list, "r") as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue

            (date, time) = line.split()[0:2]
            hh, mm, ss = time.split(':')
            yield ''.join(date.split('/')), hh, mm, ss


def make_ftpcmd(meteor_list, directory):
    '''
    検出されたログから画像をダウンロードするFTPコマンドを生成する。
    '''
    wget = "wget -nc -r -nv -nH --cut-dirs=3"
    if directory:
        wget += " -P {}".format(directory)

    for date_dir, hh, mm, ss in iter_detections(meteor_list):
        # 検出時刻から動画ファイル名を生成する。
        mp4_file = "{}/{}/{}.mp4".format(date_dir, hh, mm)
        url = "ftp://{}:{}@{}/media/mmc/record/{}".format(
            ATOM_CAM_USER, ATOM_CAM_PASS, ATOM_CAM_IP, mp4_file
        )
        print("{} {}".format(wget, url))


def detect_meteors(meteor_list, exposure=2):
    '''
    検出された流星リストから再検出(修正中)
    '''
    prev_file = None
    for date_dir, hh, mm, ss in iter_detections(meteor_list):
        file_path = Path(date_dir, hh, "{}.mp4".format(mm))

        # 同じ1分間のファイルは1回だけ処理する。
        if file_path != prev_file:
            print(file_path)
            detecter = DetectMeteor(str(file_path))
            detecter.meteor(exposure)

            prev_file = file_path


def make_movie(meteor_list, output="movie.mp4", fps=1.0):
    '''
    検出された流星リストから動画作成(未完成)

    Args:
      meteor_list: 検出された流星のログファイル
      output: 出力動画ファイル名
      fps: 出力動画のFPS
    '''
    data_dir = Path(meteor_list).parents[0]
    date_dir = Path(meteor_list).stem

    # とりあえずATOM Camサイズ
    size = (1920, 1080)
    fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
    print(f'FPS={fps}')
    video = cv2.VideoWriter(output, fourcc, fps, size)

    for date_str, hh, mm, ss in iter_detections(meteor_list):
        filename = "{}{}{}{}.jpg".format(date_str, hh, mm, ss)
        file_path = str(Path(data_dir, date_dir, filename))

        print(file_path)
        img = cv2.imread(file_path)
        if img is None:
            print("can't read: {}".format(file_path))
            continue
        video.write(img)

    video.release()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('meteors', nargs='?', help="List of detected meteors (text file)")
    parser.add_argument('-f', '--ftp', action='store_true', help='FTPコマンド作成')
    parser.add_argument('-d', '--directory', default=None, help='FTPコマンド取得先ディレクトリ名')
    parser.add_argument('-m', '--movie', action='store_true', help='検出画像から動画作成')
    parser.add_argument('-o', '--output', default='movie.mp4', help='動画ファイル名(.mp4)')
    parser.add_argument('-c', '--clock', action='store_true', help='ATOM Camの時計のチェック')
    parser.add_argument('-s', '--set_clock', action='store_true', help='ATOM Camの時計をホスト側に合わせる')
    parser.add_argument('-F', '--fps', default=1.0, type=float, help='動画生成時のFPS')
    parser.add_argument('-e', '--exposure', default=2, type=int, help='再検出時の露出時間(second)')

    args = parser.parse_args()

    if args.clock:
        check_clock()
    elif args.set_clock:
        set_clock()
    elif args.meteors is None:
        parser.error("検出ログファイル(meteors)を指定してください")
    elif args.ftp:
        make_ftpcmd(args.meteors, args.directory)
    elif args.movie:
        make_movie(args.meteors, args.output, args.fps)
    else:
        detect_meteors(args.meteors, args.exposure)
