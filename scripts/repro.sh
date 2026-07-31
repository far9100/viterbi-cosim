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
# 其餘每一個檔案——gates.csv、results_m*.csv、power*.json、saif/*.saif.gz、
# saif/MANIFEST.sha256、saif/MANIFEST_m9.sha256、tierb_manifests/*.json
# ——**必須逐位元組相同**。
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
#
# clean 一定要 hermetic：生成狀態不只在 data/。cocotb 的 pass-marker 住在
# tb/cocotb/build/_passed/，Verilator 的產物在 obj_dir/ 與 sim_build/。
# 第一次冷跑就是漏了 tb/cocotb/build ⇒ run_tier_a.py 看到 stale marker 直接跳過模擬本身，
# 於是 M3 的 C2 假性通過（回放舊計數、根本沒重跑）。少刪一個目錄，整個 M3 就沒真的重生。
banner "2. 刪光 data/ + ppa/out/ + figures/ + 所有 build 狀態"
rm -rf data ppa/out figures obj_dir sim_build tb/cocotb/build
mkdir -p data
echo "  已刪。git 現在應該看到大量 deleted："
git status --short -- data | head -5
echo "  ..."

# ---------------------------------------------------------------- 重生
banner "3. 從零重生（這是重點；耗時 2-4 小時）"
t0=$(date +%s)

# 每一步的耗時累積起來，最後印一張表。冷跑要好幾個小時，而各步驟的成本
# 是排程與取捨的依據（例如「M9 值不值得留在鏈路裡」）——把它記下來，
# 而不是讓它只存在於捲過去的終端機輸出裡。
TIMES=()

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
  local dt=$(( $(date +%s) - ts ))
  # 用 | 當分隔符，不用空格：步驟名本身含空格（"M0 env"、"M1 golden"），
  # 以空格切會把名字拆成兩個欄位，秒數就跑到名字的第二個字上去了。
  TIMES+=("$name|$dt")
  echo "--- [$name] 完成（$dt 秒）"
}

step "M0 env"    make env
step "M1 golden" make m1
step "freeze"    make freeze
step "M2 sweep"  make m2
step "M3 rtl"    make m3
step "M4 tierb"  make m4
step "M5 ppa"    make m5
# M9 必須在 figures 之前。它在 2026-07-29/30 完成，但沒有被加進這串步驟，
# 而第 2 步會把 data/ 刪光——於是 `make figures` 的 plot_m9.py 找不到 power_m9.json，
# 冷跑在這裡直接 FileNotFoundError；就算跳過圖，check_paper_numbers.py 斷言
# gates.csv 有 36 列，少了 M9 的 8 列也只會有 28 列。
# 也就是說：M7（tag `m7-repro`）坐實的那個「一鍵冷跑」宣稱，從 M9 落地那天起就是假的。
step "M9 lowpow" make m9
step "figures"   make figures
step "report"    make report
step "mutate"    make mutate

echo
echo "重生完成，共 $(( ($(date +%s) - t0) / 60 )) 分。各步驟耗時："
for e in "${TIMES[@]}"; do
  printf "  %-12s %6d 秒\n" "${e%%|*}" "${e##*|}"
done

# ---------------------------------------------------------------- 驗收
banner "4. 驗收：git status 必須只剩 data/meta_*.json 與 vectors/MANIFEST.json 的 metadata"

# figures/ 與 ppa/out/ 是 gitignore 掉的，不列入比對（它們本來就不是證據）。
DIFF=$(git status --porcelain -- data | awk '{print $2}')

# **判準原本只看 data/ —— 那是一個盲點。**
#
# `make freeze` 會重寫 `vectors/MANIFEST.json`，而它在 data/ 之外，
# 所以每一次冷跑都會默默改動這個**凍結的**測試向量清單而沒有任何人看見；
# `m7-repro`（2026-07-17）的宣稱也繼承了這個盲點。
#
# 但這個檔不能整份豁免：它裝著 46 個向量的 92 個 SHA-256（input / expected 各一），
# 那正是凍結的本體。
# 會變的只有 `metadata` 區塊（start_timestamp / git_commit / 工具版本），
# 與 data/meta_*.json 同性質。所以判準是「**除了 metadata 以外逐位元組相同**」——
# 精確地豁免該豁免的，不放寬該守的。
banner "4a. 凍結的測試向量清單：metadata 以外必須逐位元組相同"
if [ -n "$(git status --porcelain -- vectors)" ]; then
  if git show HEAD:vectors/MANIFEST.json > /tmp/mf_old.json 2>/dev/null &&
     python3 -c "
import json, sys
old = json.load(open('/tmp/mf_old.json'))
new = json.load(open('vectors/MANIFEST.json'))
old.pop('metadata', None); new.pop('metadata', None)
sys.exit(0 if old == new else 1)
"; then
    echo "  OK：46 個向量的 92 個 SHA-256 與其餘欄位完全相同，只有 metadata 變動"
    git status --short -- vectors | sed 's/^/  /'
  else
    echo "**凍結的測試向量清單在 metadata 以外也變了 —— 這是嚴重發現。**"
    git diff -- vectors/MANIFEST.json | head -40
    echo "（備份仍在 $BAK）"
    exit 1
  fi
  # vectors/ 底下除了 MANIFEST.json 以外的任何差異都是失敗（.npz 必須逐位元組重生）。
  OTHER=$(git status --porcelain -- vectors | awk '{print $2}' | grep -v '^vectors/MANIFEST.json$' || true)
  if [ -n "$OTHER" ]; then
    echo "**vectors/ 底下有 MANIFEST.json 以外的差異：**"
    echo "$OTHER" | sed 's/^/  /'
    exit 1
  fi
else
  echo "  OK：vectors/ 完全沒有差異"
fi

UNEXPECTED=""
for f in $DIFF; do
  case "$f" in
    data/meta_*.json)  ;;                       # 預期會變：時間戳 + wall time
    # 這裡原本還豁免 data/repro.log —— 但那個檔從來沒有被寫出來過（LOG 變數宣告了沒用）。
    # 一個不存在的檔案的豁免只是把判準悄悄放寬一格，刪掉。
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

# gate 數從 gates.csv 現算，不寫死。
# 這一行原本硬寫「26 個 gate」，而實際是 36——它是冷跑路徑上唯一沒有任何檢查器
# 盯著的數字，所以它腐化了兩次（gate 改名 26->27，再加上 M9 的 8 列）都沒被發現。
# 現算的成本是一行 awk，而寫死的成本是一個會說謊的成功橫幅。
N_GATES=$(awk 'NR>1' data/gates.csv | wc -l)

echo "=================================================================="
echo " 冷跑驗證**通過**。"
echo ""
echo " 刪光 data/ 從零重生之後，除了 data/meta_*.json（時間戳與 wall time，"
echo " 本來就會變）以外，**每一個檔案都逐位元組相同**："
echo "   - data/gates.csv          （$N_GATES 筆 gate 記錄）"
echo "   - data/results_m*.csv     （報告數字的唯一來源）"
echo "   - data/saif/*.saif.gz     （功耗證據：M5 的 10 個點 + M9 的 32 個點）"
echo "   - data/saif/MANIFEST.sha256 / MANIFEST_m9.sha256"
echo "   - data/tierb_manifests/*.json"
echo ""
echo " 規格書 §8 的「從零重生」宣稱，第一次成為一個被實測驗證過的事實。"
echo "=================================================================="
echo
echo "備份可以刪了：  rm $BAK"
