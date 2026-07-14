#!/usr/bin/env bash
# RTL 的三重前端檢查。**從第一個 RTL commit 起就跑。**
#
# 為什麼三個都要：它們的 SystemVerilog 前端支援度不同，而三個都是必經之路。
#   Verilator  —— Tier A / Tier B 的模擬
#   Icarus     —— G7 的 4-state 交叉檢查、M5 的 gate-level 模擬
#   Yosys 0.64 —— M5 的合成（前端最弱的一個）
#
# 第 5 週才發現 Yosys 吃不下某個 SV 構造，就是這種專案掉一週的經典死法。
#
# 注意：**不要把工具的輸出接到 head/tail 再用 if 判斷**。那樣 if 測到的是 head 的
# 結束碼，不是工具的——第一版就是這樣寫的，結果 Verilator 與 Icarus 明明失敗，
# 腳本照樣印「OK」。這正是本專案一直在防的「靜默綠燈」。
set -u
cd "$HOME/fec-cosim"
# shellcheck disable=SC1091
source scripts/env.sh

RTL="rtl/bmu.sv rtl/acs_butterfly.sv rtl/acs_array.sv rtl/minpm.sv
     rtl/traceback.sv rtl/ctrl.sv rtl/viterbi_top.sv"
FAIL=0
mkdir -p ppa/out

echo "=============================================================="
echo " 1/3  Verilator lint"
echo "=============================================================="
# shellcheck disable=SC2086
verilator --lint-only -sv -Irtl --top-module viterbi_top $RTL > /tmp/vl.log 2>&1
RC=$?
head -25 /tmp/vl.log
if [ "$RC" -eq 0 ]; then echo "  Verilator: OK"; else echo "  Verilator: FAIL (rc=$RC)"; FAIL=1; fi

echo ""
echo "=============================================================="
echo " 2/3  Icarus (-g2012)"
echo "=============================================================="
# shellcheck disable=SC2086
iverilog -g2012 -Irtl -o /tmp/iv_check.vvp -s viterbi_top $RTL > /tmp/iv.log 2>&1
RC=$?
head -25 /tmp/iv.log
if [ "$RC" -eq 0 ]; then echo "  Icarus: OK"; else echo "  Icarus: FAIL (rc=$RC)"; FAIL=1; fi

echo ""
echo "=============================================================="
echo " 3/3  Yosys 0.64（合成前端）"
echo "=============================================================="
cat > ppa/out/check.ys <<'YS'
read_verilog -sv -DSYNTHESIS -I/work/rtl \
  /work/rtl/bmu.sv /work/rtl/acs_butterfly.sv /work/rtl/acs_array.sv \
  /work/rtl/minpm.sv /work/rtl/traceback.sv /work/rtl/ctrl.sv /work/rtl/viterbi_top.sv
hierarchy -check -top viterbi_top
proc
opt -fast
stat
YS
bash ppa/orfs.sh 'yosys -q -s /work/ppa/out/check.ys' > /tmp/ys.log 2>&1
RC=$?
grep -vE '^Warning: Replacing memory' /tmp/ys.log | tail -22
if [ "$RC" -eq 0 ]; then echo "  Yosys: OK"; else echo "  Yosys: FAIL (rc=$RC)"; FAIL=1; fi

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "三個前端全部通過。"
else
  echo "有前端失敗。"
fi
exit "$FAIL"
