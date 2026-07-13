#!/usr/bin/env bash
# M0-4：建立 Python venv 並安裝釘死版本的相依套件（不含 torch，見 setup_gpu.sh）。
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

echo "--- 已安裝："
./.venv/bin/python -c "import numpy, matplotlib, pytest; print('numpy      ', numpy.__version__); print('matplotlib ', matplotlib.__version__); print('pytest     ', pytest.__version__)"
./.venv/bin/python -c "import cocotb; print('cocotb     ', cocotb.__version__)"
