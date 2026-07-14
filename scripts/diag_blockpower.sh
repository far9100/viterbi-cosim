#!/usr/bin/env bash
# report_power -instances 的輸出長什麼樣？（分區塊功耗是 R1 的救命稻草，必須解析對）
set -u
cd "$HOME/fec-cosim"
# shellcheck disable=SC1091
source scripts/env.sh

cat > ppa/out/blk.tcl <<'TCL'
read_liberty /OpenROAD-flow-scripts/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /work/ppa/out/synth/net_Q4_W10_D64.v
link_design viterbi_top
create_clock -name clk -period 10 [get_ports clk]
read_saif -scope tb_viterbi_file/dut /work/data/saif/act_Q4_W10_D64_snr3.0.saif
puts "=== POWER u_tb ==="
report_power -digits 6 -instances [get_cells u_tb]
puts "=== POWER u_acs ==="
report_power -digits 6 -instances [get_cells u_acs]
exit
TCL

bash ppa/orfs.sh 'sta -no_init -exit /work/ppa/out/blk.tcl' 2>&1 | \
  grep -vE '^$|Copyright|GPLv3|free software|certain conditions|ABSOLUTELY|show_'
