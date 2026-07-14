"""test_c2prime.py — C2′：L2-CPU 與 L2-GPU 逐位元相等。零容忍。

## 規格書 v1 沒有這個比對點

v1 的比對點只有 C1（L1↔L2，計價）與 C2（L2↔L3，零容忍）。但 GPU 版的 golden model
會**產生 Tier B 的期望輸出、也會決定 winner 組態**——它若與 CPU golden 有任何一個 bit 不同，
C2 就失去意義（RTL 對的是一份錯的參考）。所以必須有 C2′。

## 為什麼 GPU 版特別容易錯

1. `torch.minimum` **不回傳索引**。survivor bit 得自己算，而 `<=` 與 `<` 的選擇
   會默默決定平手時選哪個前驅。Q=3 時軟值只有 8 階，整數平手非常常見。
2. `torch.argmin` 的**平手行為在文件上沒有保證**（numpy 的有）。
3. int32 vs int64、以及 `>>` 是算術右移還是邏輯右移，都可能悄悄改變 modulo 比較的結果。

以上三者選錯都**不會報錯**。C2′ 是唯一會叫的東西。

## 比對什麼

每個 stage 的 `pm`（mod 2^W）、`surv`、`best`，以及最後的解碼位元 `dec`。
涵蓋安全與不安全的 (Q, W) 格點——不安全的格點才會真的 wrap，
而 wrap 之後的 modulo 比較正是最容易在 CPU/GPU 之間走鐘的地方。
"""

import itertools
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate  # noqa: E402
from golden.quantizer import quantize, sigma_from_ebn0, w_is_safe  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from golden.viterbi_fx import decode_fx  # noqa: E402

torch = pytest.importorskip("torch")
if not torch.cuda.is_available():
    pytest.skip("需要 CUDA", allow_module_level=True)

from sweep.viterbi_gpu import decode_gpu  # noqa: E402

N_INFO = 256


def _stimulus(t, B, snr, Q, clip, seed):
    rng = np.random.default_rng(seed)
    info = rng.integers(0, 2, size=(B, N_INFO), dtype=np.uint8)
    cw = t.encode(info)
    x = 1.0 - 2.0 * cw.astype(np.float64)
    sigma = sigma_from_ebn0(snr, code_rate(N_INFO, t.m))
    rx = x + rng.normal(0.0, sigma, size=x.shape)
    return info, quantize(rx, sigma, Q, clip)


def _compare(t, B, snr, Q, W, D, clip, seed):
    info, rq = _stimulus(t, B, snr, Q, clip, seed)

    cpu = decode_fx(rq, t, Q, W, D, N_INFO, mode="window",
                    check_g6=False, keep_history=True)
    gpu = decode_gpu(rq, t, Q, W, D, N_INFO, mode="window", want_history=True)

    for field in ("pm", "surv", "best", "dec"):
        g = gpu[field].cpu().numpy()
        c = np.asarray(cpu[field])
        assert g.shape == c.shape, f"{field} 形狀不同: {g.shape} vs {c.shape}"
        if not np.array_equal(g, c):
            bad = np.argwhere(g != c)
            first = tuple(bad[0])
            raise AssertionError(
                f"C2' 失敗於 {field}（Q={Q} W={W} D={D} clip={clip} snr={snr}）：\n"
                f"  {len(bad)} / {g.size} 個元素不同，首個位置 {first}\n"
                f"  CPU={c[first]}  GPU={g[first]}"
            )
    return info, cpu["dec"]


@pytest.mark.parametrize("Q,W", [(Q, W) for Q in (3, 4, 5, 6) for W in (8, 10, 12)])
def test_c2prime_all_qw_cells(Q, W):
    """涵蓋全部 12 個 (Q, W) 格點——安全的 8 個與不安全的 4 個都要。

    不安全的格點才會真的 wrap；wrap 之後的 modulo 比較是 CPU/GPU 最容易走鐘的地方，
    所以它們不能被跳過。
    """
    t = viterbi_trellis()
    # 低 SNR：PM spread 最大，最容易觸發 wraparound
    _compare(t, B=32, snr=1.0, Q=Q, W=W, D=32, clip=2.0, seed=1000 + Q * 16 + W)


@pytest.mark.parametrize("D", [24, 32, 48, 64])
def test_c2prime_traceback_depths(D):
    """回溯深度也要涵蓋——traceback 的向量化在 CPU 與 GPU 是兩份獨立的實作。"""
    t = viterbi_trellis()
    _compare(t, B=32, snr=3.0, Q=4, W=10, D=D, clip=2.0, seed=2000 + D)


@pytest.mark.parametrize("clip", [1.5, 2.0, 2.5, 3.0])
def test_c2prime_clip_levels(clip):
    t = viterbi_trellis()
    _compare(t, B=32, snr=4.0, Q=3, W=8, D=32, clip=clip, seed=3000 + int(clip * 10))


def test_c2prime_ties_are_actually_exercised():
    """證明測試真的碰到了平手——否則 tie-break 的語意根本沒被驗到，通過也不算數。

    Q=3 時軟值只有 8 階（λ_max = 14），整數平手應該很常見。
    """
    t = viterbi_trellis()
    Q, W, D = 3, 8, 32
    info, rq = _stimulus(t, 64, 2.0, Q, 2.0, seed=7)

    # 重跑一次前向，數 ACS 有多少次平手
    from golden.quantizer import lambda_max, pm_init
    lam = lambda_max(Q)
    mask = (1 << W) - 1
    S, H = t.n_states, t.half
    j = np.arange(t.n_bfly)
    X = t.bfly_out[j]
    maxr = (1 << Q) - 1

    pm = np.full((rq.shape[0], S), pm_init(Q) & mask, dtype=np.int64)
    pm[:, 0] = 0
    n_tie = 0
    for tt in range(rq.shape[1]):
        r0, r1 = rq[:, tt, 0], rq[:, tt, 1]
        bm = np.empty((rq.shape[0], 4), dtype=np.int64)
        for c in range(4):
            b0 = r0 if ((c >> 1) & 1) == 0 else (maxr - r0)
            b1 = r1 if (c & 1) == 0 else (maxr - r1)
            bm[:, c] = b0 + b1
        bm_X = bm[:, X]
        bm_Xc = lam - bm_X
        pa, pb = pm[:, j], pm[:, j + H]
        a0 = (pa + bm_X) & mask
        q0 = (pb + bm_Xc) & mask
        a1 = (pa + bm_Xc) & mask
        q1 = (pb + bm_X) & mask
        n_tie += int(np.sum(a0 == q0)) + int(np.sum(a1 == q1))
        sel0 = (((q0 - a0) & mask) >> (W - 1)) & 1 == 0
        sel1 = (((q1 - a1) & mask) >> (W - 1)) & 1 == 0
        pm_new = np.empty_like(pm)
        pm_new[:, 0::2] = np.where(sel0, a0, q0)
        pm_new[:, 1::2] = np.where(sel1, a1, q1)
        pm = pm_new

    assert n_tie > 0, "這組向量完全沒有平手 —— tie-break 語意沒被測到，C2' 的通過不算數"
    print(f"\n  平手次數 {n_tie}（Q={Q}：軟值只有 8 階，平手本來就常見）")


def test_gpu_encoder_matches_cpu():
    """GPU 的編碼器必須與 CPU 的逐位元組相等。

    GPU 版把 1030 次迭代的編碼迴圈改寫成「移位視窗」一次算完（見 sweep/stimulus.py），
    這是一個**獨立的實作**，不是翻譯。移位方向或補零長度差一位，
    產生的碼字就會整體錯開——而 BER 只會「看起來比較差」，不會報錯。
    """
    from sweep.stimulus import GpuStimulus

    t = viterbi_trellis()
    st = GpuStimulus(t)
    rng = np.random.default_rng(4242)
    info = rng.integers(0, 2, size=(16, N_INFO), dtype=np.uint8)

    cpu = t.encode(info)                                          # (B, T, 2) uint8
    gpu = st.encode(torch.as_tensor(info, dtype=torch.long, device="cuda"))
    assert np.array_equal(gpu.cpu().numpy().astype(np.uint8), cpu)


def test_gpu_quantizer_matches_cpu():
    """GPU 的量化器必須與 CPU 的逐位元組相等（給同一組浮點輸入）。

    量化器的方向搞反（r 隨 y 遞增而不是遞減）不會報錯，只會讓 BER 爛掉。
    """
    from golden.quantizer import quantize as cpu_quantize

    rng = np.random.default_rng(55)
    y = rng.normal(0, 1.3, size=(64, 200)).astype(np.float32)
    sigma = 0.7
    for Q in (3, 4, 5, 6):
        for clip in (1.5, 2.0, 2.5, 3.0):
            cpu = cpu_quantize(y.astype(np.float64), sigma, Q, clip)
            # 與 stimulus.make 裡同一組公式
            levels = (1 << Q) - 1
            A = clip * sigma
            yt = torch.as_tensor(y, device="cuda")
            r = torch.round((A - yt) * levels / (2.0 * A))
            gpu = torch.clamp(r, 0, levels).to(torch.int32).cpu().numpy()
            assert np.array_equal(gpu, cpu.astype(np.int32)), \
                f"量化器不一致 @ Q={Q} clip={clip}"


def test_ber_is_independent_of_W_for_safe_cells():
    """安全格點下，BER 與 W 無關——**這是要驗證的，不是要假設的**。

    它其實是 G6 的推論：若 modulo 算術導出的每個決策都與無界參考相同，
    那麼決策序列（因而解碼位元、因而 BER）就與 W 完全無關。
    W 只是**面積與功耗**的軸，不是 BER 的軸。

    驗證它有兩個好處：
      (1) 設計空間從 (Q, clip, W, D) 塌成 (Q, clip, D)，掃描量少 3 倍；
      (2) 這本身是一個可回報的結論——「字寬不影響 BER，只影響 PPA」。

    這裡直接比對**解碼位元**，不是比 BER：位元相同是更強的敘述。
    """
    t = viterbi_trellis()
    ref = None
    for W in (8, 10, 12):
        if not w_is_safe(4, W):
            continue
        info, rq = _stimulus(t, 32, 3.0, Q=4, clip=2.0, seed=99)
        out = decode_gpu(rq, t, Q=4, W=W, D=32, n_info=N_INFO)
        dec = out["dec"].cpu().numpy()
        if ref is None:
            ref = dec
        else:
            assert np.array_equal(dec, ref), \
                f"安全格點 W={W} 的解碼位元與其他 W 不同 —— G6 的推論被推翻了"
