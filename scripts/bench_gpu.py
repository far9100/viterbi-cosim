"""GPU 解碼器的吞吐量——決定掃描網格開多大。"""

import os
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate  # noqa: E402
from golden.quantizer import quantize, sigma_from_ebn0  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from sweep.viterbi_gpu import decode_gpu  # noqa: E402

t = viterbi_trellis()
N = 1024

# 每個 batch 的 kernel launch 次數是固定的（1030 stages x ~25 個 kernel ≈ 26k 次），
# 與 B 無關。所以 B 越大，launch 的固定成本被攤得越薄——直到記憶體撐不住為止。
print(f"{'B':>6} {'記憶體':>10} {'耗時':>9} {'吞吐':>14}")
for B in (4096, 8192, 16384, 32768):
    rng = np.random.default_rng(1)
    info = rng.integers(0, 2, size=(B, N), dtype=np.uint8)
    cw = t.encode(info)
    x = 1.0 - 2.0 * cw.astype(np.float64)
    sigma = sigma_from_ebn0(4.0, code_rate(N, t.m))
    rx = x + rng.normal(0.0, sigma, size=x.shape)
    rq = quantize(rx, sigma, 4, 2.0)

    decode_gpu(rq, t, 4, 10, 64, N)              # 暖機（cudnn / 記憶體池）
    torch.cuda.synchronize()

    t0 = time.time()
    out = decode_gpu(rq, t, 4, 10, 64, N)
    torch.cuda.synchronize()
    dt = time.time() - t0

    bits = B * N
    mem = torch.cuda.max_memory_allocated() / 1e6
    print(f"{B:>6} {mem:>8.0f} MB {dt:>8.2f}s {bits/dt/1e6:>10.1f} Mb/s")

    err = int(np.sum(out["dec"].cpu().numpy() != info))
    torch.cuda.reset_peak_memory_stats()

print()
print("CPU golden 的參考值：約 0.49 Mb/s（8 個 worker 時 1.69 Mb/s 總吞吐）")
