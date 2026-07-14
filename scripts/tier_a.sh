#!/usr/bin/env bash
# Tier A 的入口。
#   MODE=c2      安全格點：C2 零 mismatch，G6 不得誤觸發
#   MODE=g6neg   不安全格點：C2 仍要零 mismatch，但 G6 **必須**觸發
#   MODE=g7      Icarus（4-state）交叉檢查
set -eu
cd "$HOME/fec-cosim"
# shellcheck disable=SC1091
source scripts/env.sh
export PYTHONPATH="$HOME/fec-cosim"
exec .venv/bin/python tb/cocotb/run_tier_a.py
