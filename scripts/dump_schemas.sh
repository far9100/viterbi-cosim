#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for f in data/results_m1.csv data/m2_grid.csv data/m2_winners.csv data/results_m5_power.csv \
         data/results_m5_dstar.csv data/results_m5_fmax.csv data/results_m5_toggle.csv \
         data/results_m5_adc.csv data/results_m4.csv data/m3_c2.csv data/c1_quantization_loss.csv; do
  [ -f "$f" ] || continue
  echo "### $f  ($(( $(wc -l < "$f") - 1 )) 列)"
  head -2 "$f"
  echo
done
echo "### data/gates.csv（全部）"
cat data/gates.csv
