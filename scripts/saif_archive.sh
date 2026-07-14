#!/usr/bin/env bash
# SAIF 的歸檔：壓縮 + SHA-256 manifest。
#
# ## 為什麼需要這一步
#
# .gitignore 原本寫「SAIF 入庫（O(#nets)，2-10 MB/點）」。**那個估計錯了 5-10 倍**：
# 真實 netlist 有 43 萬條 net，每個 SAIF 是 30-56 MB，10 個共 466 MB。
# 466 MB 直接進 git 是永久性的 repo 膨脹。
#
# 但 SAIF 是純文字、結構高度重複 —— **gzip 有 27.6 倍**：466 MB -> 18 MB。
# 18 MB 換「功耗數字的原始證據可被任何人重新驗算」是划算的，所以原本的承諾照樣兌現，
# 只是改成壓縮存放。
#
# 原始 .saif 留在工作目錄（OpenSTA 的 read_saif 要吃未壓縮的），但不入庫。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== 壓縮 + 產生 manifest"
MAN=data/saif/MANIFEST.sha256
: > "$MAN.tmp"

total_raw=0
total_gz=0
for f in data/saif/*.saif; do
  [ -e "$f" ] || continue
  gz="$f.gz"
  # -n：不寫入時間戳，讓同樣的輸入產生逐位元組相同的 .gz（可重生性）
  gzip -9 -n -c "$f" > "$gz.tmp" && mv "$gz.tmp" "$gz"

  raw=$(stat -c %s "$f")
  gzs=$(stat -c %s "$gz")
  total_raw=$((total_raw + raw))
  total_gz=$((total_gz + gzs))

  # manifest 記的是**未壓縮**的 SAIF 的雜湊 —— 那才是 OpenSTA 真正讀進去的東西。
  # 格式必須是標準的 `<sha>  <name>` 兩欄，多加一欄（例如檔案大小）會讓
  # `sha256sum -c` 把 "name size" 當成檔名，全部報 FAILED open or read。
  sha=$(sha256sum "$f" | cut -d' ' -f1)
  printf "%s  %s\n" "$sha" "$(basename "$f")" >> "$MAN.tmp"

  printf "  %-36s %6.1f MB -> %5.1f MB (%.1fx)\n" "$(basename "$f")" \
    "$(echo "$raw" | awk '{print $1/1e6}')" \
    "$(echo "$gzs" | awk '{print $1/1e6}')" \
    "$(echo "$raw $gzs" | awk '{print $1/$2}')"
done

mv "$MAN.tmp" "$MAN"
printf "\n=== 合計：%.0f MB -> %.0f MB（%.1fx）\n" \
  "$(echo "$total_raw" | awk '{print $1/1e6}')" \
  "$(echo "$total_gz" | awk '{print $1/1e6}')" \
  "$(echo "$total_raw $total_gz" | awk '{print $1/$2}')"
echo "-> $MAN（$(wc -l < "$MAN") 個檔的 SHA-256，記的是**未壓縮**檔的雜湊）"
echo
echo "入庫的是 *.saif.gz 與 MANIFEST.sha256；未壓縮的 *.saif 留在工作目錄但不入庫。"
