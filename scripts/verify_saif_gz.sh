#!/usr/bin/env bash
# 驗證：入庫的 .saif.gz 足以重算出完全相同的結果。
# 也就是說 git clone 之後**不需要重跑 gate-level 模擬**就能驗算功耗證據。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

# **只複製 M5 的 .saif.gz。**
#
# 原本這裡是 `cp data/saif/*.saif.gz`，在目錄裡只有 M5 的 10 個檔時是對的。
# M9 歸檔之後目錄裡有 42 個 .gz，全部餵給 saif_toggle.py 會多算出 M9 的列，
# 與 results_m5_toggle.csv 比對必然不同——而失敗訊息會長得像「壓縮歸檔不足以重生結果」，
# 也就是**把一個範圍設定錯誤偽裝成證據損毀**。這與 scripts/saif_archive.sh 修掉的是同一個 bug。
#
# 分割規則與 saif_archive.sh 一致：檔名含 `_rtlv` 的屬 M9，其餘屬 M5。
rm -rf /tmp/saifgz && mkdir -p /tmp/saifgz
(cd data/saif && ls | grep '\.saif\.gz$' | grep -v _rtlv) | while read -r b; do
  cp "data/saif/$b" /tmp/saifgz/
done

python3 ppa/saif_toggle.py --saif-dir /tmp/saifgz --out /tmp/toggle_from_gz.csv >/dev/null

if diff -q data/results_m5_toggle.csv /tmp/toggle_from_gz.csv >/dev/null; then
  echo "OK：只用入庫的 .saif.gz 重算，結果與原始 .saif **逐位元組相同**。"
  echo "    -> git clone 之後不必重跑 gate-level 模擬也能驗算功耗證據。"
else
  echo "**不同！** 壓縮歸檔不足以重生結果："
  diff data/results_m5_toggle.csv /tmp/toggle_from_gz.csv | head -20
  exit 1
fi

# 兩份 manifest 都驗。M9 沒有對應的 toggle CSV 可以重算比對（它交付的是分區塊功耗，
# 不是 net 分類的翻轉率），所以 M9 的 .gz 是**只驗雜湊**——這比不驗弱，如實記在這裡。
echo
for m in MANIFEST.sha256 MANIFEST_m9.sha256; do
  echo "=== 驗證 $m（對未壓縮檔，$(wc -l < "data/saif/$m") 個檔）"
  (cd data/saif && sha256sum -c "$m" 2>/dev/null | sed 's/^/    /')
done
