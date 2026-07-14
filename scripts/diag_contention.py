"""診斷：為什麼 14 個 worker 平行時，每個點慢到跑不完？

假設：traceback 對 surv 陣列做的是**隨機 gather**。B=400 時 surv 是
400 x 1030 x 64 = 26 MB，遠大於 L3（9700X 是 32 MB）。14 個 worker 同時亂序存取
14 x 26 = 364 MB 的工作集，整個卡在 DRAM 延遲上，每個 worker 的速度掉到單執行緒的
一小部分——於是「開更多 worker」反而讓每個 job 都跑不完。

驗證方式：同一個點，分別用 1 / 4 / 8 / 14 個平行 worker 跑，比較「單一 job 的耗時」
與「總吞吐量」。若假設成立，worker 變多時單 job 耗時會超線性惡化，
而總吞吐量會在某個 worker 數之後不升反降。
"""

import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import measure_ber  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402

CFG = {"kind": "fx", "Q": 5, "clip": 2.0, "W": 12, "D": 64}
MAX_BITS = int(2.5e7)


def one(i):
    t0 = time.time()
    r = measure_ber(viterbi_trellis(), 1024, 5.5, CFG, 20260714 + i,
                    min_errors=100, max_bits=MAX_BITS, batch_frames=400)
    return time.time() - t0, r["n_bits"]


def main():
    print(f"單點：fx Q=5 clip=2.0 W=12 D=64 @ 5.5 dB，上限 {MAX_BITS:,} bits")
    print(f"{'workers':>8} {'單 job 耗時':>12} {'總吞吐':>16} {'相對 1 worker':>14}")
    base = None
    for n in (1, 4, 8, 14):
        t0 = time.time()
        with Pool(processes=n) as p:
            res = p.map(one, range(n))
        wall = time.time() - t0
        per_job = sum(r[0] for r in res) / n
        total_bits = sum(r[1] for r in res)
        thru = total_bits / wall
        if base is None:
            base = thru
        print(f"{n:>8} {per_job:>10.1f}s {thru/1e3:>12.0f} kb/s "
              f"{thru/base:>13.2f}x")


if __name__ == "__main__":
    main()
