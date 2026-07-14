"""列出還沒跑完的量測點，並實測其中一個的耗時。

之前兩次都在猜，猜錯了兩次。這次先看資料。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import measure_ber  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from scripts.m1_gate import (BATCH, CACHE, MAX_BITS, MIN_ERRORS, N_INFO,  # noqa: E402
                             SEED, _cache_key, build_jobs)

jobs = build_jobs()
pending = [j for j in jobs
           if not os.path.exists(os.path.join(CACHE, f"{_cache_key(*j)}.json"))]

print(f"待跑 {len(pending)} / {len(jobs)}：")
for name, cfg, snr in pending:
    print(f"  {name:22s} @ {snr} dB   {cfg}")

if pending:
    name, cfg, snr = pending[0]
    print(f"\n單獨計時第一個：{name} @ {snr} dB")
    t0 = time.time()
    r = measure_ber(viterbi_trellis(), N_INFO, snr, cfg, SEED,
                    min_errors=MIN_ERRORS, max_bits=MAX_BITS, batch_frames=BATCH)
    dt = time.time() - t0
    print(f"  耗時 {dt:.1f}s   BER={r['ber']:.3e}  "
          f"錯誤 {r['n_errors']}  位元 {r['n_bits']:,}")
