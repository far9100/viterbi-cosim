#!/usr/bin/env bash
set -u
cd "$HOME/fec-cosim"
# shellcheck disable=SC1091
source scripts/env.sh

SAIF=data/saif/act_Q4_W10_D64_snr3.0.saif
NET=ppa/out/synth/net_Q4_W10_D64.v

echo "=== netlist：viterbi_top 的子實例"
sed -n '/^module viterbi_top/,/^endmodule/p' "$NET" | grep -nE '^\s+\S+\s+u_\w+' | head

echo ""
echo "=== SAIF 頂層兩層的 net 名稱（dut 這一層）"
sed -n '11,14p' "$SAIF"
grep -m8 -oE '^\s+\((\w+)$' "$SAIF" | head -8

echo ""
echo "=== OpenSTA（完整輸出）"
cat > ppa/out/diag_annot.tcl <<TCL
read_liberty /OpenROAD-flow-scripts/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /work/$NET
link_design viterbi_top
create_clock -name clk -period 10 [get_ports clk]
puts "TOP_PINS [llength [get_pins -hierarchical *]]"
puts "--- read_saif -scope tb_viterbi_file/dut"
read_saif -scope tb_viterbi_file/dut /work/$SAIF
report_activity_annotation
exit
TCL
bash ppa/orfs.sh 'sta -no_init -exit /work/ppa/out/diag_annot.tcl' 2>&1 | grep -vE '^$|Copyright|GPLv3|free software|certain conditions|ABSOLUTELY'
