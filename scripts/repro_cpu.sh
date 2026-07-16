#!/usr/bin/env bash
# repro_cpu.sh —— CPU 範圍的冷跑：GPU 被其他專案佔用時能做的最強可重生性驗證。
#
# ## 為什麼需要這一支
#
# 整條鏈路裡**只有 M2 的 BER 掃描真的需要 GPU**（sweep/grid_runner.py 寫死
# device="cuda"）。而 grid_runner 只在 measure() 裡碰 CUDA、且會先跳過已快取的點——
# 所以只要**保留 data/cache_m2/（GPU 產物）**，`make m2` 會 no-op 掉 GPU、純 CPU 走完。
#
# 於是「保留 cache_m2、其餘全刪重生」就是 GPU 空出前能做的最強驗證：它會**真的**重建
# M3 的 32 個 Verilator model、重跑 Tier B、重做 gate-level 功耗與 SAIF——其中 M3 正是
# 第一次冷跑死掉、Bug A（clean 不 hermetic）要修的地方。完整宣稱（含 M2 掃描本身的重生）
# 留待 GPU 空出後由 `make repro` 坐實。
#
# ## 判準（不放寬）
#
# 除了以下兩者，每一個重生的 CSV 與 SAIF 都必須**逐位元組相同**：
#   - data/meta_*.json：記 start_timestamp 與 wall time，本來就會變。
#   - data/gates.csv 的**列序**：M0 需 GPU、無法在此重生，其 gate 列原地保留；M1-M5 的 gate
#     重跑後被 replace-by-key 移到檔尾 ⇒ 列序會變。**只比對值**（排序後必須相同）。
#
# 任何一個檔案的**值**沒能重生，就是真實發現，追查並如實記錄，不得放寬判準。
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
source scripts/env.sh

SP="/mnt/c/Users/fartw/AppData/Local/Temp/claude/C--Users-fartw-OneDrive-Desktop-github-FEC-Decoder-RTL-and-Bit-Accurate-Co-Simulation/7d878f93-5ae5-45ce-88da-1a49c78c0531/scratchpad"
banner() { echo; echo "############ $* ############"; echo; }
cache_ok() { [ "$(ls data/cache_m2/*.json 2>/dev/null | wc -l)" -eq 280 ]; }

# ---------------------------------------------------------------- 0. 前置
banner "0. 前置檢查"
# 只看**已追蹤**檔案的修改：本 script 自己可能還沒 commit（untracked），不該擋。
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "**工作區有未提交的追蹤檔修改——冷跑會把差異跟重生結果混在一起。先 commit 或 stash。**"
  git status --short --untracked-files=no
  exit 1
fi
if ! cache_ok; then
  echo "**data/cache_m2 不完整（$(ls data/cache_m2/*.json 2>/dev/null | wc -l)/280）——"
  echo "  它是 GPU 產物、在此無法重生。中止，什麼都不刪。**"
  exit 1
fi
echo "  追蹤檔乾淨、cache_m2 完整（280）"

# ---------------------------------------------------------------- 1. 備份 cache_m2（保命）
banner "1. 備份 cache_m2（GPU 產物，目前唯一副本）"
mkdir -p "$SP"
tar czf "$SP/cache_m2_backup.tar.gz" data/cache_m2
echo "  -> $SP/cache_m2_backup.tar.gz"

# ---------------------------------------------------------------- 2. 刪除 CPU 衍生產物
# **明確列舉要刪的**（deny-list），cache_m2 永遠不在其中——比「刪全部再保留白名單」安全。
# 保留：data/cache_m2、data/gates.csv、data/meta_m0_env.json、vectors/（已凍結）。
banner "2. 刪除 CPU 衍生產物 + 所有 build 狀態（保留 cache_m2 / gates.csv / meta_m0 / vectors）"
rm -f  data/results_m1.csv data/meta_m1_golden.json data/meta_m2_sweep.json
rm -f  data/m3_c2.csv data/meta_m3_rtl.json
rm -f  data/tierb.json data/results_m4.csv data/meta_m4_tierb.json
rm -rf data/tierb_manifests
rm -f  data/results_m5_power.csv data/results_m5_toggle.csv data/results_m5_dstar.csv \
       data/results_m5_fmax.csv data/results_m5_mechanism.csv data/results_m5_adc.csv \
       data/power.json data/meta_m5_ppa.json
rm -rf data/saif
rm -rf data/cache_m1 data/cache_m5
rm -rf figures ppa/out obj_dir sim_build tb/cocotb/build
if ! cache_ok; then
  echo "**cache_m2 被誤刪！立即還原並中止。**"
  tar xzf "$SP/cache_m2_backup.tar.gz"
  exit 1
fi
echo "  已刪。cache_m2 仍完整（280）。tracked 檔的 deleted 一覽："
git status --short -- data | grep '^ D' | head

# ---------------------------------------------------------------- 3. 重生
# 跳過 `make env`（M0 的 E2 硬相依 GPU）與 `make freeze`（vectors 已凍結且未被刪，
# 重跑只會churn MANIFEST.json 的 metadata）。
banner "3. 從零重生（純 CPU；估 2-2.5 小時）"
t0=$(date +%s)
step() {
  local name="$1"; shift
  local ts=$(date +%s)
  echo; echo "--- [$name] $(date +%H:%M:%S)"
  if ! "$@"; then
    echo "**[$name] 失敗 —— CPU 冷跑中止。**"
    echo "cache_m2 備份在 $SP/cache_m2_backup.tar.gz"
    exit 1
  fi
  echo "--- [$name] 完成（$(( $(date +%s) - ts )) 秒）"
}
step "M1 golden"  make m1
step "M2 gate"    make m2
step "M3 rtl"     make m3
step "M4 tierb"   make m4
step "M5 ppa"     make m5
step "figures"    make figures
step "report"     make report
step "mutate"     make mutate
echo; echo "重生完成，共 $(( ($(date +%s) - t0) / 60 )) 分。"

# ---------------------------------------------------------------- 4. 驗收
banner "4. 驗收：CSV 與 SAIF 的**值**必須逐位元組重生"
UNEXPECTED=""
for f in $(git status --porcelain -- data vectors | awk '{print $2}'); do
  case "$f" in
    data/meta_*.json) ;;      # 預期會變：時間戳
    data/gates.csv)   ;;      # 列序會變（見檔頭），下面單獨做值比對
    *) UNEXPECTED="$UNEXPECTED $f" ;;
  esac
done

echo "有差異的檔案："
git status --short -- data vectors | sed 's/^/  /'
echo

FAIL=0
if [ -n "$UNEXPECTED" ]; then
  echo "**以下檔案的值沒能逐位元組重生（真實發現，不放寬判準）：**"
  for f in $UNEXPECTED; do
    echo "  === $f"
    git diff --stat -- "$f" | sed 's/^/    /'
  done
  FAIL=1
fi

# gates.csv：只准列序不同，值必須相同
if ! git diff --quiet data/gates.csv 2>/dev/null; then
  git show HEAD:data/gates.csv | sort > /tmp/g_old.txt
  sort data/gates.csv > /tmp/g_new.txt
  if diff -q /tmp/g_old.txt /tmp/g_new.txt >/dev/null; then
    echo "gates.csv：值完全相同、只有列序不同（partial run 的已知產物，可接受）"
  else
    echo "**gates.csv 的值有變（不只列序）—— 真實發現：**"
    diff /tmp/g_old.txt /tmp/g_new.txt | head -20
    FAIL=1
  fi
fi

echo
if [ "$FAIL" -ne 0 ]; then
  echo "=================================================================="
  echo " CPU 冷跑驗證**失敗**。上面列出的檔案沒能重生其值——這是真實發現，去查原因。"
  echo " cache_m2 備份在 $SP/cache_m2_backup.tar.gz"
  echo "=================================================================="
  exit 1
fi

echo "=================================================================="
echo " CPU 冷跑驗證**通過**。"
echo ""
echo " 保留 cache_m2、刪光 M1/M3/M4/M5 + SAIF 重生後，除 meta_*.json（時間戳）與"
echo " gates.csv 的列序外，**每一個 CSV 與 SAIF 都逐位元組相同**："
echo "   - results_m1 / m3_c2 / tierb(+manifests) / results_m4 / results_m5_* / results_m2"
echo "   - saif/*.saif.gz + saif/MANIFEST.sha256"
echo ""
echo " 只剩 M2 的 BER 掃描（cache_m2）需要 GPU。完整的『刪光一切從零重生』宣稱，"
echo " 留待 GPU 空出後由 make repro 坐實。"
echo "=================================================================="
