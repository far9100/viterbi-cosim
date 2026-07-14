#!/usr/bin/env bash
# 預先登記的時間戳是否真的早於量測？——這是整篇報告的科學主張所繫。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== docs/falsification.md 被**加入**的 commit"
git log --diff-filter=A --format='%h  %ci  %s' -- docs/falsification.md

echo
echo "=== docs/energy_model.md 被**加入**的 commit"
git log --diff-filter=A --format='%h  %ci  %s' -- docs/energy_model.md

echo
echo "=== 功耗量測（data/power.json）被**加入**的 commit"
git log --diff-filter=A --format='%h  %ci  %s' -- data/power.json

echo
echo "=== SAIF 證據被**加入**的 commit"
git log --diff-filter=A --format='%h  %ci  %s' -- data/saif/ | head -2
