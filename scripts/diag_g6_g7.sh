#!/usr/bin/env bash
# 直接看 g6neg 與 g7 的原始輸出。
set -u
cd "$HOME/fec-cosim"
# shellcheck disable=SC1091
source scripts/env.sh
export PYTHONPATH="$HOME/fec-cosim"

echo "=============================================="
echo " G6 正向：Q=4 W=10（安全），assertion **不該**響"
echo "=============================================="
FEC_SIM=verilator FEC_Q=4 FEC_W=10 FEC_D=32 FEC_NINFO=256 \
  FEC_VECTORS=boundary_Q4_W10 FEC_REPO="$PWD" \
  FEC_WORKDIR="$PWD/tb/cocotb/build/diag_g6ok" \
  .venv/bin/python tb/cocotb/_run_group.py > /tmp/g6ok.log 2>&1
echo "  exit=$?  'G6 violated' 次數=$(grep -c 'G6 violated' /tmp/g6ok.log)  (應為 0)"
grep 'C2_STATS' /tmp/g6ok.log || echo "  (無 C2_STATS)"

echo ""
echo "=============================================="
echo " G6 負向：Q=4 W=8（不安全），assertion **必須**響"
echo "=============================================="
FEC_SIM=verilator FEC_Q=4 FEC_W=8 FEC_D=32 FEC_NINFO=256 \
  FEC_VECTORS=negative_Q4_W8 FEC_REPO="$PWD" \
  FEC_WORKDIR="$PWD/tb/cocotb/build/diag_g6" \
  .venv/bin/python tb/cocotb/_run_group.py > /tmp/g6.log 2>&1
echo "  exit=$?  'G6 violated' 次數=$(grep -c 'G6 violated' /tmp/g6.log)  (應 > 0)"
grep -m2 'G6 violated' /tmp/g6.log | sed 's/^/    /'
grep 'C2_STATS' /tmp/g6.log || echo "  (無 C2_STATS)"

echo ""
echo "=============================================="
echo " G7：Icarus + cocotb 的 libm 衝突"
echo "=============================================="
echo "  oss-cad-suite 的 libm：$(ls -la "$OSS_CAD/lib/libm.so.6" 2>/dev/null | awk '{print $NF}')"
echo "  系統的 libm：          /lib/x86_64-linux-gnu/libm.so.6"
echo ""
echo "  試 LD_PRELOAD 系統的 libm："
LD_PRELOAD=/lib/x86_64-linux-gnu/libm.so.6 \
FEC_SIM=icarus FEC_Q=4 FEC_W=10 FEC_D=32 FEC_NINFO=256 \
  FEC_VECTORS=directed_allzero,directed_allone FEC_REPO="$PWD" \
  FEC_WORKDIR="$PWD/tb/cocotb/build/diag_g7" \
  .venv/bin/python tb/cocotb/_run_group.py > /tmp/g7.log 2>&1
echo "  exit=$?"
grep 'C2_STATS' /tmp/g7.log || echo "  (無 C2_STATS)"
grep -iE 'GLIBC|mismatch|PASS=|FAIL=' /tmp/g7.log | head -4 | sed 's/^/    /'
