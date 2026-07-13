#!/usr/bin/env bash
# 確認容器可用，並取得 OpenSTA 三個關鍵指令的正確語法（不靠猜，實測）。
set -eu
cd "$(dirname "$0")/../.."

cat > /tmp/probe.tcl <<'TCL'
puts "=== read_saif"
help read_saif
puts "=== read_power_activities"
help read_power_activities
puts "=== report_activity_annotation"
help report_activity_annotation
puts "=== report_power"
help report_power
exit
TCL
cp /tmp/probe.tcl ppa/out/probe.tcl

./ppa/orfs.sh 'yosys -V; echo "--- openroad:"; openroad -version; echo "--- sta:"; sta -version; echo "--- 指令語法:"; sta -no_init -exit /work/ppa/out/probe.tcl'
