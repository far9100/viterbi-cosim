#!/usr/bin/env bash
# repro.sh —— **冷跑**：刪光 data/ 從零重生，逐位元組驗證。
#
# ## 這在驗什麼
#
# 規格書 §8 與 README 都宣稱：
#
#     刪掉 data/ 後，make 能從零重生所有數字與圖表，且 check_paper_numbers.py
#     回報 mismatches: 0。
#
# **在 2026-07-15 之前，這件事從來沒有被測試過。** 而且當時的 Makefile 根本做不到
# （sweep/ber/report 直接印「尚未開始」）。一個從未被測試過的可重生性宣稱，
# 正是這個專案一路在抓的那種東西——所以這裡把它變成一個真的會失敗的測試。
#
# ## 判準（很強，因為 data/ 底下的 CSV 與 SAIF 全部是 git 追蹤的）
#
#     刪光 -> 重生 -> git status
#     必須**只剩 data/meta_*.json 有差異**（它們記 start_timestamp 與 wall time，本來就會變）
#
# 其餘每一個檔案——gates.csv、results_m*.csv、saif/*.saif.gz、saif/MANIFEST.sha256、
# tierb_manifests/*.json——**必須逐位元組相同**。
#
# 任何一個檔案沒能逐位元組重生，就是一個**真實發現**，要追查並如實記錄，
# 不得把判準放寬。
#
# ## 退路
#
# git 追蹤的檔案本來就能用 `git checkout -- data/` 救回。真正救不回的是 gitignore 掉的
# 快取（data/cache_*）與原始的 .saif（重跑要 35 分）。所以開跑前先 tar 一份，
# 中止時還原，成本歸零。
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
source scripts/env.sh

BAK="${REPRO_BAK:-/tmp/fec-repro-backup.tar}"
LOG="data/repro.log"

banner() { echo; echo "############ $* ############"; echo; }

# ---------------------------------------------------------------- 前置檢查
banner "0. 前置檢查"

if [ -n "$(git status --porcelain)" ]; then
  echo "**工作區不乾淨——冷跑會把差異跟重生結果混在一起，無法判讀。先 commit 或 stash。**"
  git status --short
  exit 1
fi
echo "  工作區乾淨 OK"

# M2 的掃描硬相依 GPU（sweep/grid_runner.py 寫死 device=\"cuda\"）。
# 刪快取之前一定要先確認，否則會卡死在半路。
bash scripts/check_gpu.sh || {
  echo "**GPU 不可用 —— 中止，什麼都沒刪。**"; exit 1; }

# ---------------------------------------------------------------- 備份
banner "1. 備份（中止時的退路）"
tar cf "$BAK" data ppa/out 2>/dev/null || true
echo "  -> $BAK  ($(du -h "$BAK" | cut -f1))"
echo "  中止時還原：  cd $REPO && tar xf $BAK && git checkout -- data/"

# ---------------------------------------------------------------- 刪光
banner "2. 刪光 data/ + ppa/out/ + figures/"
rm -rf data ppa/out figures
mkdir -p data
echo "  已刪。git 現在應該看到大量 deleted："
git status --short -- data | head -5
echo "  ..."

# ---------------------------------------------------------------- 重生
banner "3. 從零重生（這是重點；耗時 2-4 小時）"
t0=$(date +%s)

step() {
  local name="$1"; shift
  local ts=$(date +%s)
  echo
  echo "--- [$name] $(date +%H:%M:%S)"
  if ! "$@"; then
    echo "**[$name] 失敗 —— 冷跑中止。**"
    echo "還原：  cd $REPO && tar xf $BAK && git checkout -- data/"
    exit 1
  fi
  echo "--- [$name] 完成（$(( $(date +%s) - ts )) 秒）"
}

step "M0 env"    make env
step "M1 golden" make m1
step "freeze"    make freeze
step "M2 sweep"  make m2
step "M3 rtl"    make m3
step "M4 tierb"  make m4
step "M5 ppa"    make m5
step "figures"   make figures
step "report"    make report
step "mutate"    make mutate

echo
echo "重生完成，共 $(( ($(date +%s) - t0) / 60 )) 分。"

# ---------------------------------------------------------------- 驗收
banner "4. 驗收：git status 必須只剩 data/meta_*.json"

# figures/ 與 ppa/out/ 是 gitignore 掉的，不列入比對（它們本來就不是證據）。
DIFF=$(git status --porcelain -- data | awk '{print $2}')

UNEXPECTED=""
for f in $DIFF; do
  case "$f" in
    data/meta_*.json)  ;;                       # 預期會變：時間戳 + wall time
    data/repro.log)    ;;                       # 本檔自己的 log
    *) UNEXPECTED="$UNEXPECTED $f" ;;
  esac
done

echo "有差異的檔案："
git status --short -- data | sed 's/^/  /'
echo

if [ -n "$UNEXPECTED" ]; then
  echo "**冷跑驗證失敗：以下檔案沒能逐位元組重生**"
  for f in $UNEXPECTED; do
    echo "  $f"
  done
  echo
  echo "這是一個真實發現。逐檔看差異："
  for f in $UNEXPECTED; do
    echo "  === $f"
    git diff --stat -- "$f" | sed 's/^/    /'
  done
  echo
  echo "**不要把判準放寬——去查為什麼。**"
  echo "（備份仍在 $BAK）"
  exit 1
fi

echo "=================================================================="
echo " 冷跑驗證**通過**。"
echo ""
echo " 刪光 data/ 從零重生之後，除了 data/meta_*.json（時間戳與 wall time，"
echo " 本來就會變）以外，**每一個檔案都逐位元組相同**："
echo "   - data/gates.csv          （27 個 gate）"
echo "   - data/results_m*.csv     （報告數字的唯一來源）"
echo "   - data/saif/*.saif.gz     （功耗證據）"
echo "   - data/saif/MANIFEST.sha256"
echo "   - data/tierb_manifests/*.json"
echo ""
echo " 規格書 §8 的「從零重生」宣稱，第一次成為一個被實測驗證過的事實。"
echo "=================================================================="
echo
echo "備份可以刪了：  rm $BAK"
