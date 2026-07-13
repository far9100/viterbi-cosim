#!/usr/bin/env bash
# 只跑 PPA 流程的合成半段（不需要 iverilog），先驗證容器 + syn.ys 是對的。
set -eu
cd "$HOME/fec-cosim"
chmod +x ppa/*.sh ppa/smoke/*.sh scripts/*.sh 2>/dev/null || true
mkdir -p ppa/out/smoke

bash ppa/orfs.sh 'yosys -q -s /work/ppa/smoke/syn.ys'

echo "=== stat"
sed -n '/Printing statistics/,/^$/p' ppa/out/smoke/counter_stat.txt | head -30

echo ""
echo "=== netlist 用到的 cell 種類"
grep -oE 'sky130_fd_sc_hd__[a-z0-9_]+' ppa/out/smoke/counter_net.v | sort | uniq -c | sort -rn

echo ""
echo "=== netlist 的 wire 宣告（看向量有沒有被保留、有沒有 escaped identifier）"
grep -E '^\s*(wire|input|output)' ppa/out/smoke/counter_net.v | head -20
