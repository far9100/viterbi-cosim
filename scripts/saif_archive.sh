#!/usr/bin/env bash
# SAIF 的歸檔：壓縮 + SHA-256 manifest。**以里程碑為範圍**，用法 `saif_archive.sh m5|m9`。
#
# ## 為什麼需要這一步
#
# .gitignore 原本寫「SAIF 入庫（O(#nets)，2-10 MB/點）」。**那個估計錯了 5-10 倍**：
# 真實 netlist 有 43 萬條 net，每個 SAIF 是 30-56 MB，10 個共 466 MB。
# 466 MB 直接進 git 是永久性的 repo 膨脹。
#
# 但 SAIF 是純文字、結構高度重複 —— **gzip 有 25-28 倍**：M5 的 466 MB -> 18 MB，
# M9 的 1063 MB -> 42 MB。用這點空間換「功耗數字的原始證據可被任何人重新驗算」是划算的，
# 所以原本的承諾照樣兌現，只是改成壓縮存放。
#
# 原始 .saif 留在工作目錄（OpenSTA 的 read_saif 要吃未壓縮的），但不入庫。
#
# ## 為什麼要吃里程碑參數（2026-07-31）
#
# 第一版無條件掃 `data/saif/*.saif`，寫死單一個 MANIFEST.sha256。當時目錄裡只有 M5 的
# 10 個檔，所以看不出問題。M9 落地後目錄裡變成 42 個檔，於是**一次增量的 `make m5`
# 就會把 M9 的 32 個 SAIF 壓進 M5 的 manifest**，把一份「M5 功耗證據的清單」
# 悄悄變成「碰巧在硬碟上的所有 SAIF 的清單」。
#
# 完整冷跑剛好遮住這個 bug（目錄從空的開始，M5 跑的時候 M9 的檔還不存在），
# 這正是它一直沒被發現的原因——也正是為什麼判準不能只靠冷跑。
#
# 分割規則：檔名含 `_rtlv` 的屬 M9（`rtl_lowpower/` 的 B0′ 與 B1′ 兩個變體），
# 其餘屬 M5。這是一個**完全分割**：每個 .saif 恰好屬於一個里程碑，
# 底下的 leftover 檢查會在有檔案兩邊都不屬於時直接失敗，
# 避免將來新增變體時它從所有 manifest 裡靜靜消失。
set -euo pipefail
cd "$(dirname "$0")/.."

MS="${1:-}"
case "$MS" in
  m5) MAN=data/saif/MANIFEST.sha256;    SEL=(grep -v _rtlv); DESC="M5（full-parallel B0）" ;;
  m9) MAN=data/saif/MANIFEST_m9.sha256; SEL=(grep    _rtlv); DESC="M9（rtl_lowpower B0′/B1′）" ;;
  *)  echo "用法：$0 m5|m9"; exit 1 ;;
esac

echo "=== 壓縮 + 產生 manifest：$DESC"

# 完全分割檢查：不屬於任何里程碑的 SAIF 是一個錯誤，不是可以忽略的殘留。
LEFTOVER=$(cd data/saif && ls 2>/dev/null | grep '\.saif$' | grep -v _rtlv | grep -v '^act_Q[0-9]' || true)
if [ -n "$LEFTOVER" ]; then
  echo "**有 SAIF 不屬於任何里程碑，歸檔規則已經與產出對不上：**"
  echo "$LEFTOVER" | sed 's/^/  /'
  exit 1
fi

FILES=$(cd data/saif && ls 2>/dev/null | grep '\.saif$' | "${SEL[@]}" || true)
if [ -z "$FILES" ]; then
  echo "**data/saif/ 底下沒有屬於 $MS 的 SAIF —— 沒有東西可以歸檔。**"
  exit 1
fi

: > "$MAN.tmp"
total_raw=0
total_gz=0
for b in $FILES; do
  f="data/saif/$b"
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
  printf "%s  %s\n" "$sha" "$b" >> "$MAN.tmp"

  printf "  %-40s %6.1f MB -> %5.1f MB (%.1fx)\n" "$b" \
    "$(echo "$raw" | awk '{print $1/1e6}')" \
    "$(echo "$gzs" | awk '{print $1/1e6}')" \
    "$(echo "$raw $gzs" | awk '{print $1/$2}')"
done

# manifest 依檔名排序，讓它與產出的先後無關（`ls` 已經是排序的，這裡把它變成明文保證）。
sort -k2 "$MAN.tmp" -o "$MAN.tmp"
mv "$MAN.tmp" "$MAN"
printf "\n=== 合計：%.0f MB -> %.0f MB（%.1fx）\n" \
  "$(echo "$total_raw" | awk '{print $1/1e6}')" \
  "$(echo "$total_gz" | awk '{print $1/1e6}')" \
  "$(echo "$total_raw $total_gz" | awk '{print $1/$2}')"
echo "-> $MAN（$(wc -l < "$MAN") 個檔的 SHA-256，記的是**未壓縮**檔的雜湊）"
echo
echo "入庫的是 *.saif.gz 與 $(basename "$MAN")；未壓縮的 *.saif 留在工作目錄但不入庫。"
