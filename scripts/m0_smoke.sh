#!/usr/bin/env bash
# M0 的煙霧測試驅動：檢查工具是否齊備，然後跑 PPA 全流程。
set -u
cd "$HOME/fec-cosim"
# shellcheck disable=SC1091
source scripts/env.sh

chmod +x ppa/*.sh ppa/smoke/*.sh scripts/*.sh 2>/dev/null

echo "=== 工具檢查"
FAIL=0
for t in iverilog verilator docker python3; do
  if command -v "$t" >/dev/null 2>&1; then
    printf '  OK      %-12s %s\n' "$t" "$(command -v "$t")"
  else
    printf '  MISSING %-12s\n' "$t"
    FAIL=1
  fi
done
[ "$FAIL" -eq 0 ] || exit 3

echo ""
exec bash ppa/smoke/run.sh
