#!/usr/bin/env bash
# run.sh —— PPA 煙霧測試：counter 走完整條 gate-level 功耗流程。
#
# 驗收標準：OpenSTA 的 activity annotation coverage > 99%。
#
# 這是 M0 最重要的一步。整條流程（Yosys -> gate-level sim -> VCD -> SAIF -> OpenSTA）
# 是全專案唯一零複用的部分——RISC-V 專案的 gate-level power 是 vectorless 的
# （假設 activity=0.2/duty=0.5），從未做過真實 activity 標註，其論文自己把
# 「workload SAIF 的真實-activity EDP」列為未竟事項。
#
# 這條流程與 Viterbi 解碼器毫無相依，所以現在就能跑。第 1 週失敗還救得回來；
# 第 5 週帶著 deadline 才發現 annotation 是 0%，就沒救了。
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

OUT="ppa/out/smoke"
MODELS="ppa/models/sky130_fd_sc_hd"
CYCLES="${CYCLES:-2000}"

mkdir -p "$OUT"

echo "=============================================================="
echo " 1/4  Yosys 合成（ORFS 容器）"
echo "=============================================================="
./ppa/orfs.sh 'yosys -q -s /work/ppa/smoke/syn.ys'
echo "  netlist: $(grep -c '^ *sky130_fd_sc_hd__' $OUT/counter_net.v || true) 個 cell 實例"
grep -E 'Chip area|Number of cells' "$OUT/counter_stat.txt" | sed 's/^/  /' || true

echo ""
echo "=============================================================="
echo " 2/4  Gate-level 模擬（Icarus + sky130 behavioral models）"
echo "=============================================================="
# 只編譯 netlist 真正用到的 cell，不是全部 2310 個檔——後者 elaborate 會慢到不能用。
CELLS=$(grep -oE 'sky130_fd_sc_hd__[a-z0-9_]+' "$OUT/counter_net.v" | sort -u)
echo "  netlist 用到的 cell 種類："
echo "$CELLS" | sed 's/^/    /'

FILELIST="$OUT/cells.f"
: > "$FILELIST"
INCS=""
for c in $CELLS; do
  # cell 的 wrapper 檔在 cells/<cellname>/ 底下。直接 find，不從名字推目錄——
  # drive strength 的後綴規則不是每個 cell 都一致，硬推會漏。
  f=$(find "$MODELS/cells" -name "$c.v" | head -1)
  if [ -n "$f" ]; then
    echo "$f" >> "$FILELIST"
    INCS="$INCS -I$(dirname "$f")"
  else
    echo "  警告：找不到 $c 的行為模型"
  fi
done

# 為什麼每個 cell 目錄都要一個 -I：
#   iverilog 解析 `include 時是相對於 **-I 的搜尋路徑與 CWD**，不是相對於「包含它的那個檔案」。
#   （實測：把模型攤平會讓 ../../models/... 解不開；不加 -I 則連同目錄的裸檔名也解不開。）
#   加了 cell 自己的目錄當 -I 之後，兩種 include 同時解得開：
#     裸檔名   sky130_fd_sc_hd__a21oi.v         -> <cells/a21oi>/sky130_fd_sc_hd__a21oi.v
#     相對路徑 ../../models/udp_dff_p/x.v       -> <cells/dfxtp>/../../models/udp_dff_p/x.v
#
# FUNCTIONAL：選 .functional.v（純布林，無需 SDF 反標註的 specify timing）
# UNIT_DELAY=#1：給每個 cell 一個時間單位的延遲，讓結構性 hazard（glitch）能傳播。
#                零延遲模擬完全沒有 glitch，會系統性低估動態功耗。
# 不定義 USE_POWER_PINS：Yosys 的 netlist 沒有 power pin。
# shellcheck disable=SC2086
iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY='#1' \
  $INCS \
  -o "$OUT/gl.vvp" \
  -f "$FILELIST" \
  "$OUT/counter_net.v" \
  ppa/smoke/tb_gl.sv

echo "  編譯成功，跑 $CYCLES cycles"

echo ""
echo "=============================================================="
echo " 3/4  VCD -> SAIF（串流，VCD 不落地）"
echo "=============================================================="
# gate-level VCD 是 30-180 KB/cycle。用 FIFO 讓它完全不碰硬碟：
# vvp 一邊寫，vcd2saif.py 一邊讀，SAIF 是 O(#nets) 而非 O(#nets x cycles)。
FIFO="$OUT/dump.vcd"
rm -f "$FIFO"
mkfifo "$FIFO"

python3 ppa/vcd2saif.py --vcd "$FIFO" --out "$OUT/counter.saif" &
SAIF_PID=$!

vvp "$OUT/gl.vvp" +vcdfile="$FIFO" +cycles="$CYCLES" > "$OUT/sim.log" 2>&1

wait $SAIF_PID
rm -f "$FIFO"

echo "  SAIF: $(du -h "$OUT/counter.saif" | cut -f1)"

echo ""
echo "=============================================================="
echo " 4/4  OpenSTA：SAIF 標註 + 功耗"
echo "=============================================================="
./ppa/orfs.sh 'sta -no_init -exit /work/ppa/smoke/power.tcl' 2>&1 | tee "$OUT/power.log"

echo ""
echo "=============================================================="
python3 ppa/check_annotation.py "$OUT/power.log"
