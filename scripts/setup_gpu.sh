#!/usr/bin/env bash
# M0-6：安裝 torch（cu128）並驗證 sm_120 可用。
#
# 為什麼不能直接 pip install torch：PyPI 的預設 wheel 是 CPU-only 或只含較舊的 SM 架構，
# 在 RTX 5070（Blackwell, sm_120）上會出現 "no kernel image available for execution on the device"。
# 必須從 cu128 index 取 wheel。規格書 §5 明列「環境設置的第一步是跑一個最小整數 kernel 驗證 GPU 可用」。
set -euo pipefail
cd "$(dirname "$0")/.."

./.venv/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cu128

echo "--- torch 安裝完成，執行 sm_120 整數 kernel 驗證："
./.venv/bin/python scripts/gpu_smoke.py
