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
#
# ## 為什麼現在跑兩個目錄（2026-08-01）
#
# `rtl_lowpower/` 是 M9 的 B0′/B1′ 兩態所合成的 RTL —— 也就是 −42.7% 功耗與
# −11.02% 面積這些**已發表數字所依據的原始碼**。而它先前：
#
#   * 不被本腳本 lint（這裡只列了 `rtl/`）
#   * 不進 Tier A（`_run_group.py` 寫死 `rtl/`）
#   * 不進 Tier B（`tier_b.py` 寫死 `rtl/`）
#
# 它唯一的檢查是閘級的 `ppa/verify_cg.py`，而那道檢查在 M10 之前還驗錯了 netlist。
# 一份沒有經過任何前端檢查的 RTL，能不能被三個工具吃下去，全靠「它跟 rtl/ 很像」
# 在假設。這裡把假設換成檢查。
set -u
cd "$HOME/fec-cosim"
# shellcheck disable=SC1091
source scripts/env.sh

MODULES="bmu.sv acs_butterfly.sv acs_array.sv minpm.sv traceback.sv ctrl.sv viterbi_top.sv"
DIRS="${FEC_RTL_DIRS:-rtl rtl_lowpower}"
FAIL=0
mkdir -p ppa/out

for DIR in $DIRS; do
  RTL=""
  for m in $MODULES; do RTL="$RTL $DIR/$m"; done

  echo "=============================================================="
  echo " 目錄 $DIR"
  echo "=============================================================="

  echo "-- 1/3  Verilator lint"
  # shellcheck disable=SC2086
  verilator --lint-only -sv -I"$DIR" --top-module viterbi_top $RTL > /tmp/vl.log 2>&1
  RC=$?
  head -25 /tmp/vl.log
  if [ "$RC" -eq 0 ]; then echo "  Verilator($DIR): OK"
  else echo "  Verilator($DIR): FAIL (rc=$RC)"; FAIL=1; fi

  echo ""
  echo "-- 2/3  Icarus (-g2012)"
  # shellcheck disable=SC2086
  iverilog -g2012 -I"$DIR" -o /tmp/iv_check.vvp -s viterbi_top $RTL > /tmp/iv.log 2>&1
  RC=$?
  head -25 /tmp/iv.log
  if [ "$RC" -eq 0 ]; then echo "  Icarus($DIR): OK"
  else echo "  Icarus($DIR): FAIL (rc=$RC)"; FAIL=1; fi

  echo ""
  echo "-- 3/3  Yosys 0.64（合成前端）"
  {
    printf 'read_verilog -sv -DSYNTHESIS -I/work/%s' "$DIR"
    for m in $MODULES; do printf ' \\\n  /work/%s/%s' "$DIR" "$m"; done
    printf '\nhierarchy -check -top viterbi_top\nproc\nopt -fast\nstat\n'
  } > ppa/out/check.ys
  bash ppa/orfs.sh 'yosys -q -s /work/ppa/out/check.ys' > /tmp/ys.log 2>&1
  RC=$?
  grep -vE '^Warning: Replacing memory' /tmp/ys.log | tail -22
  if [ "$RC" -eq 0 ]; then echo "  Yosys($DIR): OK"
  else echo "  Yosys($DIR): FAIL (rc=$RC)"; FAIL=1; fi
  echo ""
done

if [ "$FAIL" -eq 0 ]; then
  echo "所有目錄的三個前端全部通過（$DIRS）。"
else
  echo "有前端失敗。"
fi
exit "$FAIL"
