#!/usr/bin/env bash
# 驗證：入庫的 .saif.gz 足以重算出完全相同的結果。
# 也就是說 git clone 之後**不需要重跑 gate-level 模擬**就能驗算功耗證據。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

rm -rf /tmp/saifgz && mkdir -p /tmp/saifgz
cp data/saif/*.saif.gz /tmp/saifgz/

python3 ppa/saif_toggle.py --saif-dir /tmp/saifgz --out /tmp/toggle_from_gz.csv >/dev/null

if diff -q data/results_m5_toggle.csv /tmp/toggle_from_gz.csv >/dev/null; then
  echo "OK：只用入庫的 .saif.gz 重算，結果與原始 .saif **逐位元組相同**。"
  echo "    -> git clone 之後不必重跑 gate-level 模擬也能驗算功耗證據。"
else
  echo "**不同！** 壓縮歸檔不足以重生結果："
  diff data/results_m5_toggle.csv /tmp/toggle_from_gz.csv | head -20
  exit 1
fi

echo
echo "=== 驗證 MANIFEST.sha256（對未壓縮檔）"
cd data/saif && sha256sum -c MANIFEST.sha256 2>/dev/null | sed 's/^/    /'
