"""m1_measure.py — 只跑量測、只填快取。閘門的判定在 m1_gate.py。

## 為什麼要把量測與判定拆開

harness 對背景指令有 10 分鐘上限。把「跑 97 個點」和「評 5 道閘門」綁在一起，
會變成：跑不完 -> 被砍 -> 連判定都做不了。拆開之後：

  m1_measure.py   一輪一輪填快取，每輪結束就落地，被砍最多損失一輪
  m1_gate.py      全部快取齊備後才跑，幾秒鐘就結束

## 為什麼一輪一輪跑，而不是把 19 個點一次丟給 Pool

一次丟給 Pool 時，被砍的瞬間**所有還在跑的 worker 都白做**。跑到 95% 的 job
和跑到 5% 的 job 一樣，什麼都不留。分輪之後，每一輪結束就有 8 個點確定落地。

再加上時間預算：只要剩餘時間不夠再跑一輪，就乾脆不開始，直接乾淨地結束。
"""

import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.m1_gate import CACHE, _cache_key, _job, build_jobs  # noqa: E402

WORKERS = 8          # 實測的吞吐峰值，見 scripts/diag_contention.py
BUDGET = 420.0       # 秒。留足餘裕給 10 分鐘的上限。
ROUND_ESTIMATE = 140.0


def main():
    jobs = build_jobs()
    pending = [j for j in jobs
               if not os.path.exists(os.path.join(CACHE, f"{_cache_key(*j)}.json"))]

    print(f"總共 {len(jobs)} 點，快取 {len(jobs) - len(pending)}，待跑 {len(pending)}")
    sys.stdout.flush()

    t0 = time.time()
    rnd = 0
    while pending:
        elapsed = time.time() - t0
        if elapsed + ROUND_ESTIMATE > BUDGET:
            print(f"時間預算用盡（已用 {elapsed:.0f}s），乾淨結束。"
                  f"還剩 {len(pending)} 點，再跑一次本 script 即可續做。")
            return 1

        batch, pending = pending[:WORKERS], pending[WORKERS:]
        rnd += 1
        tr = time.time()
        with Pool(processes=WORKERS) as p:
            p.map(_job, batch, chunksize=1)
        dt = time.time() - tr
        print(f"  第 {rnd} 輪：{len(batch)} 點 / {dt:.0f}s "
              f"（{dt/len(batch):.0f}s/點）  剩 {len(pending)}")
        sys.stdout.flush()

    print(f"\n全部 {len(jobs)} 點量測完成（{time.time() - t0:.0f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
