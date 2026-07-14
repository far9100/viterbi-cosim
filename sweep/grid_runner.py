"""grid_runner.py — GPU 設計空間掃描與 winner 選擇。

## 設計空間為什麼是 (Q, clip, D) 而不是 (Q, clip, W, D)

規格書 §5 說要掃 (Q, clip, W, D) × SNR。但 **W 不是 BER 的軸**：

    G6 說「modulo 算術導出的每個決策 == 無界參考導出的決策」。
    若 G6 成立（安全格點），決策序列與 W 完全無關 => 解碼位元與 W 無關 => BER 與 W 無關。

這是推論，不是假設——`sweep/test_c2prime.py::test_ber_is_independent_of_W_for_safe_cells`
直接比對**解碼位元**驗證了它（比比 BER 更強）。

於是：
  - BER 的軸是 (Q, clip, D)：4 x 4 x 4 = 64 個組態
  - W 只是**面積與功耗**的軸，M5 才用得到
  - 每個 Q 的**最小安全 W** 由字寬界唯一決定（Q=3→8, Q=4→10, Q=5→10, Q=6→12），
    PPA 上根本沒有選擇餘地——這本身是一個結論

不安全的 4 個格點另外跑，用來把「高 SNR 出現 BER floor、低 SNR 完全正常」那個著名症狀
畫出來——那正是 G6 存在的理由。
"""

import hashlib
import json
import os
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate  # noqa: E402
from golden.quantizer import w_is_safe  # noqa: E402
from golden.ref_float import commsim  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from scripts.gates import DATA  # noqa: E402
from sweep.stimulus import GpuStimulus  # noqa: E402
from sweep.viterbi_gpu import decode_gpu  # noqa: E402

N_INFO = 1024
SEED = 20260714
BATCH = 32768          # 實測 31 Mb/s / 1.5 GB，見 scripts/bench_gpu.py

CACHE = os.path.join(DATA, "cache_m2")

QS = (3, 4, 5, 6)
CLIPS = (1.5, 2.0, 2.5, 3.0)
DS = (24, 32, 48, 64)
SNRS = (4.0, 4.5, 5.0, 5.5)
UNSAFE = ((4, 8), (5, 8), (6, 8), (6, 10))
UNSAFE_SNRS = (2.0, 3.0, 4.0, 5.0, 6.0, 7.0)


def min_safe_W(Q):
    """該 Q 底下最小的安全 W。由 docs/wordlength_bound.md 的界唯一決定，沒有選擇餘地。"""
    for W in (8, 10, 12):
        if w_is_safe(Q, W):
            return W
    raise ValueError(Q)


def _key(cfg):
    payload = json.dumps({k: str(v) for k, v in sorted(cfg.items())}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def measure(Q, clip, W, D, snr, min_errors=400, max_bits=int(2e8)):
    """單一 (組態, SNR) 點的 BER。完成當下寫入快取，被砍掉不用重跑。"""
    cfg = {"Q": Q, "clip": clip, "W": W, "D": D, "snr": snr,
           "n_info": N_INFO, "seed": SEED, "min_err": min_errors,
           "max_bits": max_bits, "batch": BATCH}
    k = _key(cfg)
    path = os.path.join(CACHE, f"{k}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)

    t = viterbi_trellis()
    R = code_rate(N_INFO, t.m)
    st = GpuStimulus(t)

    # torch 的 CUDA 產生器：給定 seed 後是確定的。每個 (組態, SNR) 點各自一條串流。
    gen = torch.Generator(device="cuda")
    gen.manual_seed((SEED * 1000003 + int(k[:8], 16)) % (2 ** 63))

    n_err = n_bits = 0
    per_frame = []
    while n_err < min_errors and n_bits < max_bits:
        # 激勵整段留在 GPU 上。第一版把它留在 CPU（numpy 產 3370 萬個高斯亂數
        # + 1030 次迭代的 Python 編碼迴圈），GPU 因此空轉，整體只有 6.7 Mb/s。
        info, rq = st.make(BATCH, N_INFO, snr, Q, clip, R, gen)
        dec = decode_gpu(rq, t, Q, W, D, N_INFO)["dec"]

        e = (dec.to(torch.long) != info)
        pf = e.sum(dim=1).cpu().numpy()          # 只把「每個 frame 的錯誤數」搬回 CPU
        per_frame.extend(pf.tolist())
        n_err += int(pf.sum())
        n_bits += int(e.numel())
        del rq, dec, e, info

    _, _, _, metrics = commsim()
    _, lo, hi = metrics.cluster_robust_ci(np.array(per_frame), N_INFO)

    r = {"Q": Q, "clip": clip, "W": W, "D": D, "snr_db": snr,
         "ber": n_err / n_bits, "n_errors": n_err, "n_bits": n_bits,
         "ci_low": float(lo), "ci_high": float(hi)}

    os.makedirs(CACHE, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(r, f)
    os.replace(tmp, path)
    return r


def build_jobs():
    """(Q, clip, W, D, SNR)。W 一律取該 Q 的最小安全值——它不影響 BER，只影響 PPA。"""
    jobs = []
    for Q in QS:
        W = min_safe_W(Q)
        for clip in CLIPS:
            for D in DS:
                for s in SNRS:
                    jobs.append((Q, clip, W, D, s))
    # 不安全格點：畫出 BER floor
    for Q, W in UNSAFE:
        for s in UNSAFE_SNRS:
            jobs.append((Q, 2.0, W, 32, s))
    return jobs


def run(budget=420.0):
    """跑到時間預算用盡就乾淨結束。快取讓下一次接著跑。"""
    jobs = build_jobs()
    pending = [j for j in jobs
               if not os.path.exists(os.path.join(
                   CACHE, f"{_key({'Q': j[0], 'clip': j[1], 'W': j[2], 'D': j[3], 'snr': j[4], 'n_info': N_INFO, 'seed': SEED, 'min_err': 400, 'max_bits': int(2e8), 'batch': BATCH})}.json"))]

    print(f"總共 {len(jobs)} 點，快取 {len(jobs) - len(pending)}，待跑 {len(pending)}")
    sys.stdout.flush()

    t0 = time.time()
    for i, j in enumerate(pending, 1):
        if time.time() - t0 > budget:
            print(f"時間預算用盡（{time.time()-t0:.0f}s），乾淨結束。"
                  f"還剩 {len(pending) - i + 1} 點，再跑一次即可續做。")
            return 1
        measure(*j)
        if i % 20 == 0:
            print(f"   {i}/{len(pending)}  ({time.time()-t0:.0f}s)")
            sys.stdout.flush()

    print(f"全部 {len(jobs)} 點量測完成（{time.time()-t0:.0f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(run(budget=float(os.environ.get("BUDGET", "420"))))
