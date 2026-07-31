#!/usr/bin/env bash
# 在 ORFS Docker container 內執行一道指令，並把 repo 掛在 /work。
#
# 為什麼需要這個 wrapper：Yosys / OpenROAD / OpenSTA / Sky130 PDK 全部只存在於
# openroad/orfs:latest 這個 image 裡（Windows 與 WSL 的 PATH 上都沒有）。
# RISC-V 專案雖然用過同一個 image，但它**從未把 docker run 的掛載指令記錄下來**，
# 只在報告裡用散文提到——所以這一行必須重建，並且入庫。
#
# --user：讓容器內產生的檔案歸屬於呼叫者，否則 ppa/out/ 下的產物會變成 root 所有，
#          後續 script 無法覆寫。
# --entrypoint：image 的預設 entrypoint 預期是在 flow 目錄下跑 make，我們要的是直接下指令。
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# **釘 digest，不用 :latest。**
#
# 整條 PPA 鏈路（面積、Fmax、SAIF 功耗、d*）都由這個 image 裡的
# Yosys / OpenROAD / OpenSTA / sky130hd PDK 產生。`:latest` 一旦被上游推新版，
# 所有已發表的 PPA 數字都會變，而 repo 裡沒有任何東西說得出當時用的是哪一版
# —— 那等於整個 M5 與 M9 的可重現性掛在一個會浮動的標籤上。
# 版本現在也會進每一次 run 的 metadata（scripts/gates.py 的 _eda_versions）。
#
# 要升級：改這一行，並在 CHANGELOG 記錄，然後重跑 M5 + M9 並比對數字變化。
IMAGE="${FEC_ORFS_IMAGE:-openroad/orfs@sha256:a3e793752297cfea1e26e6013b4f43b629a9f074d0341df03d8521b72bc8ace7}"

# source env.sh 是必要的：image 內 yosys 在 /usr/local/bin（PATH 上找得到），
# 但 openroad 與 sta 在 /OpenROAD-flow-scripts/tools/install/ 底下，
# 不 source env.sh 就會得到 "openroad: command not found"。實測確認。
exec docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$REPO:/work" \
  -w /work \
  -e HOME=/tmp \
  --entrypoint /bin/bash \
  "$IMAGE" -c "source /OpenROAD-flow-scripts/env.sh >/dev/null 2>&1; $*"
