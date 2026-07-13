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
IMAGE="openroad/orfs:latest"

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
