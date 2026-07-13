#!/usr/bin/env bash
# 重跑 M0 閘門並修正 metadata。
#
# 為什麼要重跑：第一次跑 m0_gate.py 時 repo 還沒有任何 commit，HEAD 不存在，
# 於是 metadata 裡的 git_commit 是 "unknown"、git_dirty 是 true。
# 依 CLAUDE.md §5.3，一個無法追溯到 (seed, 組態, commit) 的量測點不是證據——
# 這條規則對 M0 的環境閘門同樣適用，不能因為「只是環境檢查」就放過。
set -eu
cd "$HOME/fec-cosim"
# shellcheck disable=SC1091
source scripts/env.sh

# gates.csv 是附加寫入的，重跑會再加三列。先清掉舊的那三列（它們的 metadata 不可追溯）。
rm -f data/gates.csv data/meta_m0_env.json

.venv/bin/python scripts/m0_gate.py

echo ""
echo "=== metadata 的可追溯性"
.venv/bin/python - <<'PY'
import json
md = json.load(open("data/meta_m0_env.json"))
for k in ("git_commit", "git_dirty", "start_timestamp"):
    print(f"  {k:18} {md[k]}")
PY
