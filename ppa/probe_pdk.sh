#!/usr/bin/env bash
# 找出 sky130hd 的 LEF 與 site 名稱（physical synthesis 需要）。
set -euo pipefail
cd "$(dirname "$0")/.."
bash ppa/orfs.sh 'P=/OpenROAD-flow-scripts/flow/platforms/sky130hd; echo "=== lef/"; ls $P/lef/; echo; echo "=== SITE"; grep -i "^SITE" $P/lef/*.tlef; echo; echo "=== 平台目錄"; ls $P'
