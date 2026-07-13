# power.tcl —— 用 SAIF 標註的真實 switching activity 算 counter 的功耗（OpenSTA 3.1.0）。
#
# 這是整條 PPA 流程的驗收點。關鍵在 read_saif 的 -scope：
#   SAIF 的根是 testbench（tb/dut/...），設計的根是 counter 本身。
#   scope 打錯 -> annotation coverage 0% -> OpenSTA 退回 set_power_activity 的預設猜測，
#   而症狀會偽裝成「功耗竟然不隨輸入改變」。這正是規格書 §7 明令禁止的
#   「用預設 toggle-rate 猜測」，卻不會有任何錯誤訊息。
#
# report_activity_annotation 就是這件事的誠實度量：它會講出到底標註到了幾條 net。

read_liberty /OpenROAD-flow-scripts/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /work/ppa/out/smoke/counter_net.v
link_design counter

# 100 MHz，與 tb_gl.sv 的時脈一致
create_clock -name clk -period 10 [get_ports clk]

read_saif -scope tb/dut /work/ppa/out/smoke/counter.saif

puts "=== ACTIVITY ANNOTATION ==="
report_activity_annotation -report_unannotated

puts "=== POWER ==="
report_power -digits 6

exit
