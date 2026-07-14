#!/usr/bin/env bash
# 驗證兩件事：
#   (1) 有 GPU 時，C2' 同時驗 cpu 與 cuda 兩條路
#   (2) 沒有 GPU 時，C2' **仍然會跑**（驗 torch 的邏輯），而且閘門不會因為「沒跑」而綠燈
cd "$HOME/fec-cosim"

echo "=============================================="
echo " 有 GPU"
echo "=============================================="
.venv/bin/python -m pytest sweep/test_c2prime.py -q 2>&1 | tail -1
.venv/bin/python scripts/m2_gate.py 2>&1 | grep -E "C2'|全綠|失敗" | head -3

echo ""
echo "=============================================="
echo " 模擬 GPU 完全不可用（CUDA_VISIBLE_DEVICES=\"\"）"
echo "=============================================="
export CUDA_VISIBLE_DEVICES=""
.venv/bin/python -m pytest sweep/test_c2prime.py -q 2>&1 | tail -1
.venv/bin/python scripts/m2_gate.py 2>&1 | grep -E "C2'|全綠|失敗" | head -3
