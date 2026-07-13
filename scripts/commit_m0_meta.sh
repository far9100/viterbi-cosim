#!/usr/bin/env bash
# 把可追溯的 M0 gate metadata 補進來。
set -eu
cd "$HOME/fec-cosim"

git add -A
git commit -q -F - <<'MSG'
M0：重跑閘門，使 metadata 可追溯到 commit

第一次跑 m0_gate.py 時 repo 還沒有任何 commit，HEAD 不存在，
metadata 的 git_commit 落成 "unknown"。依 CLAUDE.md §5.3，
一個無法追溯到 (seed, 組態, commit) 的量測點不是證據——
這條規則對環境閘門同樣適用，不能因為「只是環境檢查」就放過。

三道閘門的結果不變（E1/E2/E3 全綠），只是 metadata 現在指得回 ae9e151。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG

git tag -f -a m0-env -m "M0: 環境與 gate-level 功耗流程驗收通過（E1/E2/E3 全綠）" >/dev/null 2>&1

echo "=== git log"
git --no-pager log --oneline -2
echo ""
echo "=== 工作區"
git status --short | head -3
echo "(空白 = 乾淨)"
