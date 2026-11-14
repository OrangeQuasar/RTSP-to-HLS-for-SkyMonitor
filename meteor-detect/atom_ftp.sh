#!/bin/bash

# 下記の接続情報を自分の環境に合わせて修正してください(環境変数でも指定可)。
ATOMCAM_IP="${ATOM_CAM_IP:-192.168.2.110}"
ATOMCAM_USER="${ATOM_CAM_USER:-root}"
ATOMCAM_PASS="${ATOM_CAM_PASS:-atomcam2}"

ATOMCAM_FTP="ftp://${ATOMCAM_USER}:${ATOMCAM_PASS}@${ATOMCAM_IP}/media/mmc/record"

if [ $# -ne 3 ] ; then
    echo "Usage: atom_ftp.sh yyyymmdd start_hour end_hour"
    echo '  ex. atom_ftp.sh 20220104 1 2'
    exit 1
fi

DATE=$1

for hour in $(seq "$2" "$3")
do
    hh=$(printf "%02d" "$hour")
    echo "wget -nc -r -nv -nH --cut-dirs=3 ${ATOMCAM_FTP}/${DATE}/${hh}"
    wget -nc -r -nv -nH --cut-dirs=3 "${ATOMCAM_FTP}/${DATE}/${hh}"
done
