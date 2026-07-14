"""freeze_vectors.py — 凍結 C2 的測試向量（M1 的交付物之一）。

## 凍結的是什麼

**輸入**逐位元組凍結；**期望輸出**只存 SHA-256 摘要。

    vectors/<name>.npz    量化後的軟值 rq、組態 (Q,W,D)、以及產生它的 seed
    vectors/MANIFEST.json 每個向量的輸入雜湊 + 期望輸出（bm/pm/surv/dec）的雜湊

為什麼不把 pm / surv 的完整歷史存進去：一個 frame 的 pm 是 1030 × 64 個整數，
存幾十個向量就是幾百 MB，而且它是**可重生的**——M3 只要從凍結的輸入重跑 golden model
就能得到期望輸出。真正需要被釘死的是「輸入」與「golden 沒有偷偷改過」，
前者靠位元組凍結，後者靠 SHA-256。

這與 CLAUDE.md §5.1(d) 一致：「frozen test vectors carry SHA-256 digests」。

## 向量的組成（規格書 §4 Tier A）

1. 定向：全零、全一、單一 impulse、已知碼字 + 1-bit / 2-bit / burst 錯誤
2. 約束隨機：隨機資料 x 隨機 SNR，涵蓋每個安全的 (Q, W, D) 組態
3. 邊界：低 SNR 長 frame，故意把 PM 逼近 wraparound
4. 負向：4 個先驗不安全的 (Q, W) 格點——G6 的 assertion 必須在這些向量上觸發
"""

import hashlib
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate  # noqa: E402
from golden.quantizer import quantize, sigma_from_ebn0, w_is_safe  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from golden.viterbi_fx import decode_fx  # noqa: E402
from scripts.gates import REPO, collect_metadata  # noqa: E402

VEC_DIR = os.path.join(REPO, "vectors")
N_INFO = 256          # 向量用短 frame：C2 是逐 stage 比對，不需要長 frame 才有鑑別力
SEED = 20260714


def _sha(*arrays):
    h = hashlib.sha256()
    for a in arrays:
        a = np.ascontiguousarray(a)
        h.update(str(a.dtype).encode())
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def _make_rx(t, info, ebn0_db, rng, flip=None):
    """編碼 -> BPSK -> AWGN。flip 給定時，在指定位置注入硬性的位元翻轉。"""
    R = code_rate(N_INFO, t.m)
    sigma = sigma_from_ebn0(ebn0_db, R)
    cw = t.encode(info)
    if flip is not None:
        for (f, ti, ci) in flip:
            cw[f, ti, ci] ^= 1
    x = 1.0 - 2.0 * cw.astype(np.float64)
    rx = x + rng.normal(0.0, sigma, size=x.shape)
    return rx, sigma


def build():
    t = viterbi_trellis()
    rng = np.random.default_rng(SEED)
    vecs = []

    zeros = np.zeros((1, N_INFO), dtype=np.uint8)
    ones = np.ones((1, N_INFO), dtype=np.uint8)
    impulse = np.zeros((1, N_INFO), dtype=np.uint8)
    impulse[0, N_INFO // 2] = 1

    # ---- 1. 定向 ----
    for name, info, flip in [
        ("directed_allzero", zeros, None),
        ("directed_allone", ones, None),
        ("directed_impulse", impulse, None),
        # 已知碼字 + 錯誤模式（高 SNR，讓錯誤純粹來自人為注入）
        ("directed_err1", zeros, [(0, 10, 0)]),
        ("directed_err2", zeros, [(0, 10, 0), (0, 10, 1)]),
        ("directed_burst", zeros, [(0, 20 + k, k % 2) for k in range(6)]),
    ]:
        rx, sigma = _make_rx(t, info, 8.0, rng, flip)
        vecs.append((name, info, rx, sigma, 4, 10, 32))

    # ---- 2. 約束隨機：涵蓋每個安全的 (Q, W) x D ----
    for Q, W in itertools.product((3, 4, 5, 6), (8, 10, 12)):
        if not w_is_safe(Q, W):
            continue
        for D in (24, 32, 48, 64):
            snr = float(rng.uniform(0.0, 8.0))
            info = rng.integers(0, 2, size=(2, N_INFO), dtype=np.uint8)
            rx, sigma = _make_rx(t, info, snr, rng)
            vecs.append((f"rand_Q{Q}_W{W}_D{D}", info, rx, sigma, Q, W, D))

    # ---- 3. 邊界：低 SNR，PM spread 最大 ----
    for Q in (3, 4, 5, 6):
        W = 8 if Q == 3 else (10 if Q <= 5 else 12)
        info = rng.integers(0, 2, size=(4, N_INFO), dtype=np.uint8)
        rx, sigma = _make_rx(t, info, 0.0, rng)      # 0 dB：最惡劣
        vecs.append((f"boundary_Q{Q}_W{W}", info, rx, sigma, Q, W, 32))

    # ---- 4. 負向：4 個先驗不安全的格點，G6 必須觸發 ----
    for Q, W in [(4, 8), (5, 8), (6, 8), (6, 10)]:
        info = rng.integers(0, 2, size=(2, N_INFO), dtype=np.uint8)
        rx, sigma = _make_rx(t, info, 0.0, rng)
        vecs.append((f"negative_Q{Q}_W{W}", info, rx, sigma, Q, W, 32))

    return t, vecs


def main():
    os.makedirs(VEC_DIR, exist_ok=True)
    t, vecs = build()
    manifest = {"metadata": collect_metadata({"run": "freeze_vectors"}),
                "n_info": N_INFO, "seed": SEED, "vectors": []}

    n_safe = n_neg = 0
    for name, info, rx, sigma, Q, W, D in vecs:
        rq = quantize(rx, sigma, Q, clip=2.0)
        out = decode_fx(rq, t, Q, W, D, N_INFO, mode="window", check_g6=True)

        path = os.path.join(VEC_DIR, f"{name}.npz")
        np.savez_compressed(path, rq=rq.astype(np.int16), info=info,
                            Q=Q, W=W, D=D, n_info=N_INFO)

        entry = {
            "name": name, "Q": Q, "W": W, "D": D,
            "n_frames": int(info.shape[0]),
            "safe": bool(w_is_safe(Q, W)),
            "input_sha256": _sha(rq.astype(np.int16)),
            "expected_sha256": _sha(out["bm"], out["pm"], out["surv"], out["dec"]),
            "g6_ok": bool(out["g6_ok"]),
            "g6_first_stage": int(out["g6_first"]),
            "max_pm_spread": int(out["spread"].max()),
        }
        manifest["vectors"].append(entry)

        if name.startswith("negative"):
            n_neg += 1
            assert not out["g6_ok"], f"{name} 先驗不安全，G6 必須觸發"
        elif entry["safe"]:
            n_safe += 1
            assert out["g6_ok"], f"{name} 是安全格點，G6 不該觸發"

    with open(os.path.join(VEC_DIR, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"凍結 {len(vecs)} 個測試向量 -> vectors/")
    print(f"  安全格點  {n_safe} 個：G6 全部未觸發")
    print(f"  負向格點  {n_neg} 個：G6 全部觸發（這是必須的）")
    print("\n  負向測試的證據（G6 在哪個 stage 觸發、當時的 PM spread）：")
    for e in manifest["vectors"]:
        if e["name"].startswith("negative"):
            bound = 14 * ((1 << e["Q"]) - 1) + 1
            print(f"    Q={e['Q']} W={e['W']:2d}: 第 {e['g6_first_stage']:3d} 個 stage 觸發，"
                  f"實測 spread 最大 {e['max_pm_spread']:4d}，"
                  f"2^(W-1)={1 << (e['W']-1):4d}，安全門檻需 > {bound}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
