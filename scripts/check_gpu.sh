#!/usr/bin/env bash
# 冷跑前的 GPU 檢查（R1）。
#
# sweep/grid_runner.py:85 硬寫死 torch.Generator(device="cuda")，M2 的掃描**需要 GPU**。
# 而這台機器的 GPU 有其他專案在用。冷跑會刪掉 data/cache_m2，
# 所以**必須在刪任何東西之前**確認 GPU 拿得到，否則會把自己卡死在半路。
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "=== nvidia-smi"
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu \
           --format=csv,noheader 2>&1 | sed 's/^/  /'

echo
echo "=== 目前佔用 GPU 的 process"
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>&1 \
  | sed 's/^/  /' || true

echo
echo "=== torch 這一側"
python3 - <<'PY'
import torch
ok = torch.cuda.is_available()
print(f"  cuda available : {ok}")
if ok:
    free, total = torch.cuda.mem_get_info()
    print(f"  device         : {torch.cuda.get_device_name(0)}")
    print(f"  VRAM 可用      : {free/1e9:.1f} / {total/1e9:.1f} GB")
    # grid_runner 的 BATCH=32768，實測要 ~1.5 GB。留兩倍餘裕。
    need = 3.0
    print(f"  M2 掃描約需     : {need:.1f} GB（BATCH=32768，實測 ~1.5 GB，留兩倍餘裕）")
    print()
    if free / 1e9 < need:
        print(f"  **VRAM 不足（{free/1e9:.1f} GB < {need:.1f} GB）—— 不要開始冷跑**")
        raise SystemExit(1)
    print("  OK：GPU 可用，冷跑可以進行。")
else:
    print()
    print("  **torch 看不到 CUDA —— M2 冷跑無法進行，不要刪快取**")
    raise SystemExit(1)
PY
