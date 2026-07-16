"""gen_stimulus.py — 產生 Tier B 的激勵與期望輸出。

## 規格書 v1 的要求被廢除，不是放寬

v1 §4 要求「C++ 端的 AWGN + 量化器必須與 L2 位元級一致：用同一組固定 seed 的測試向量
先做 10⁵ bits 的 C++↔L2 全等比對」。**這在工程上做不到**：numpy 的 PCG64 + ziggurat
與任何獨立寫的 C++ RNG 都不可能逐位元組相同，除非共用實作——而共用實作又讓那個
「等價比對」變成同義反覆。

正確的做法是**讓 C++ 端沒有 RNG、也沒有量化器**：

    gen_stimulus.py (L2/GPU)  ->  stimulus.bin    packed Q-bit 軟值
                              ->  expected.bits   packed 解碼位元
                              ->  manifest.json   兩者的 SHA-256 + seed + 全部參數

    tb/cpp/sim_main.cpp       ->  讀 stimulus、驅動 DUT、與 expected XOR、數 mismatch

這比 v1 的要求**更強**：Tier-B 的激勵**就是** L2 的激勵，逐位元組相同，附雜湊。
沒有「兩份實作要碰巧相同」的問題，因為只有一份。

AWGN 的正確性另外驗（經驗變異數 vs N0/2），留在 golden/ 這一側——那是它該待的地方。

## 檔案格式

    stimulus.bin   每個 stage 兩個 byte：r0, r1（Q <= 6，放得下一個 byte）
                   總長 = n_frames × T × 2
    expected.bits  packed 解碼位元，一個 byte 8 個，**LSB 先**（numpy 的 bitorder='little'）
                   總長 = ceil(n_frames × NINFO / 8)
"""

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate  # noqa: E402
from golden.quantizer import quantize, sigma_from_ebn0  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from golden.viterbi_fx import decode_fx  # noqa: E402
from scripts.gates import collect_metadata  # noqa: E402

CHUNK = 2048         # 一次算幾個 frame（記憶體與速度的折衷）


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def generate(Q, W, D, clip, snr_db, n_frames, n_info, seed, outdir, use_gpu=True):
    t = viterbi_trellis()
    T = n_info + t.m
    R = code_rate(n_info, t.m)
    sigma = sigma_from_ebn0(snr_db, R)

    tag = f"Q{Q}_W{W}_D{D}_snr{snr_db}"
    os.makedirs(outdir, exist_ok=True)
    stim_path = os.path.join(outdir, f"stim_{tag}.bin")
    exp_path = os.path.join(outdir, f"exp_{tag}.bits")
    man_path = os.path.join(outdir, f"manifest_{tag}.json")

    gpu = None
    if use_gpu:
        try:
            import torch
            if torch.cuda.is_available():
                from sweep.viterbi_gpu import decode_gpu
                gpu = decode_gpu
        except Exception:
            gpu = None

    rng = np.random.default_rng([seed, Q, W, D, int(snr_db * 10)])
    t0 = time.time()

    with open(stim_path, "wb") as fs, open(exp_path, "wb") as fe:
        done = 0
        while done < n_frames:
            b = min(CHUNK, n_frames - done)
            info = rng.integers(0, 2, size=(b, n_info), dtype=np.uint8)
            cw = t.encode(info)
            x = 1.0 - 2.0 * cw.astype(np.float64)
            rx = x + rng.normal(0.0, sigma, size=x.shape)
            rq = quantize(rx, sigma, Q, clip)                # (b, T, 2) int64

            if gpu is not None:
                dec = gpu(rq, t, Q, W, D, n_info)["dec"].cpu().numpy()
            else:
                dec = decode_fx(rq, t, Q, W, D, n_info, mode="window",
                                check_g6=False, keep_history=False)["dec"]

            # 激勵：每個 stage 兩個 byte
            fs.write(rq.astype(np.uint8).tobytes())
            # 期望：packed bits，LSB 先
            fe.write(np.packbits(dec.reshape(-1), bitorder="little").tobytes())

            done += b

    dt = time.time() - t0
    n_bits = n_frames * n_info

    # 入庫的 manifest 只含可逐位元組重生的內容（設定 + SHA-256 + 位元組數）。
    # gen_seconds（wall-clock）與 metadata（start_timestamp / git_commit，每次都變）**不入檔**
    # ——否則 manifest 永遠無法逐位元組重生（冷跑抓到過）。run 層級的 metadata 已完整記在
    # data/meta_m4_tierb.json（冷跑已豁免），per-point 的那份是多餘的。
    manifest = {
        "tag": tag,
        "Q": Q, "W": W, "D": D, "clip": clip,
        "snr_db": snr_db, "n_frames": n_frames, "n_info": n_info,
        "T": T, "n_bits": n_bits, "seed": seed,
        "code_rate": R, "sigma": float(sigma),
        "generator": "gpu" if gpu is not None else "cpu-golden",
        "stimulus_file": os.path.basename(stim_path),
        "expected_file": os.path.basename(exp_path),
        "stimulus_sha256": _sha256_file(stim_path),
        "expected_sha256": _sha256_file(exp_path),
        "stimulus_bytes": os.path.getsize(stim_path),
        "expected_bytes": os.path.getsize(exp_path),
    }
    with open(man_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # 回傳值另附 gen_seconds 供 console 即時回饋（不入檔）。
    return {**manifest, "gen_seconds": round(dt, 1)}


def verify(man_path):
    """重跑之後用來對帳：檔案的 SHA-256 必須與 manifest 相符。

    這是 CLAUDE.md §5.1(d) 的「凍結目標的位元組對帳」。
    """
    with open(man_path) as f:
        m = json.load(f)
    d = os.path.dirname(man_path)
    ok_s = _sha256_file(os.path.join(d, m["stimulus_file"])) == m["stimulus_sha256"]
    ok_e = _sha256_file(os.path.join(d, m["expected_file"])) == m["expected_sha256"]
    return ok_s and ok_e, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--Q", type=int, required=True)
    ap.add_argument("--W", type=int, required=True)
    ap.add_argument("--D", type=int, required=True)
    ap.add_argument("--clip", type=float, required=True)
    ap.add_argument("--snr", type=float, required=True)
    ap.add_argument("--frames", type=int, required=True)
    ap.add_argument("--ninfo", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=20260714)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cpu", action="store_true", help="不用 GPU（GPU 被別的專案佔用時）")
    a = ap.parse_args()

    m = generate(a.Q, a.W, a.D, a.clip, a.snr, a.frames, a.ninfo, a.seed,
                 a.out, use_gpu=not a.cpu)
    print(f"  {m['tag']}: {m['n_frames']} frames / {m['n_bits']:,} bits  "
          f"({m['stimulus_bytes']/1e6:.0f} MB stim, {m['gen_seconds']}s, "
          f"{m['generator']})")
    print(f"    stimulus sha256 {m['stimulus_sha256'][:16]}…")
    print(f"    expected sha256 {m['expected_sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
