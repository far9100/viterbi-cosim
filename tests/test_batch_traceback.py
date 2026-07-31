"""test_batch_traceback.py — B2 的 golden 語意（mode='batch'）與凍結的交叉檢查。

語意與判準凍結於 `docs/memory_traceback_baseline.md`（B2 量測開跑前提交）：

* §1   batch（one-pointer）回溯：每 D 個 stage 追 2D 步，丟最新的 D、輸出最舊的 D，
       有效回溯深度 ∈ [D, 2D]。
* §3.3 **C-B1**：`batch(D)` 與 `window(D)` 的解碼位元不一致率 < 1%。
* §3.3 **C-B2**：兩者在 1e-5 的 required Eb/N0 差落在 ±0.076 dB 內。

## 這兩條為什麼是「與 C2 獨立」的

C2 會拿 RTL 的解碼位元對 golden 的 `batch` 比。但**如果 golden 的 batch 本身寫錯了
（例如丟錯半邊、回走步數算錯），而 RTL 恰好照同一個誤解實作，C2 照樣零 mismatch。**
所以要有一條不依賴 batch 自己的檢查：把它對已經被 C2 驗證過幾億個 stage 的
`window` 比。batch 的有效深度 ≥ D，所以它的 BER 只可能**相同或更好**，
不可能顯著更差 —— 這是一條由演算法保證的方向性，可以拿來當判準。
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.quantizer import quantize, sigma_from_ebn0  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from golden.viterbi_fx import decode_fx  # noqa: E402

Q, W, CLIP, N_INFO = 4, 10, 2.5, 1024
SEED = 20260801

# docs/memory_traceback_baseline.md §3.3 寫死的容差，事後不得放寬
CB1_MAX_DISAGREE = 0.01        # 1%
CB2_NOISE_FLOOR_DB = 0.076     # C1 的量測雜訊地板


def _run(D, snr, B=200):
    t = viterbi_trellis()
    rng = np.random.default_rng(SEED)
    info = rng.integers(0, 2, size=(B, N_INFO), dtype=np.uint8)
    x = 1.0 - 2.0 * t.encode(info).astype(np.float64)
    sigma = sigma_from_ebn0(snr, N_INFO / (2.0 * (N_INFO + t.m)))
    rq = quantize(x + rng.normal(0.0, sigma, size=x.shape), sigma, Q, CLIP)
    win = decode_fx(rq, t, Q, W, D, N_INFO, mode="window", check_g6=False)["dec"]
    bat = decode_fx(rq, t, Q, W, D, N_INFO, mode="batch", check_g6=False)["dec"]
    return info, win, bat


@pytest.mark.parametrize("D", [32, 64])
@pytest.mark.parametrize("snr", [3.0, 4.0, 5.0])
def test_cb1_batch_agrees_with_window(D, snr):
    """**C-B1**：不一致率 < 1%。

    超過門檻代表 batch 的指標算術錯了（丟錯半邊、回走步數錯、或環狀緩衝的
    index 繞錯）—— 那類錯誤不會拋例外，只會讓解出來的位元悄悄偏掉。
    """
    _, win, bat = _run(D, snr)
    disagree = float(np.mean(win != bat))
    assert disagree < CB1_MAX_DISAGREE, (
        f"D={D} snr={snr}：batch 與 window 的不一致率 {disagree * 100:.4f}% "
        f"超過凍結門檻 {CB1_MAX_DISAGREE * 100}%")


@pytest.mark.parametrize("D", [32, 64])
def test_cb2_batch_ber_is_not_worse(D):
    """**C-B2 的方向性部分**：batch 的 BER 不得顯著差於 window。

    batch 的有效深度 ∈ [D, 2D]，全部 ≥ D，所以它看得比 window 遠或一樣遠，
    BER 只可能相同或更好。顯著更差就代表實作錯了。

    這裡用「錯誤位元數」直接比，而不是換算成 dB —— 換算需要跑到 1e-5，
    那是 M14 的量測工作；單元測試只驗方向性，容差取 C1 的雜訊地板換算成的
    相對寬鬆值（BER 在 3 dB 附近對 dB 的斜率很陡，±0.076 dB 遠大於這裡的差異）。
    """
    info, win, bat = _run(D, 3.0, B=400)
    n_win = int(np.sum(win != info))
    n_bat = int(np.sum(bat != info))
    assert n_bat <= n_win * 1.5 + 10, (
        f"D={D}：batch 的錯誤位元 {n_bat} 明顯多於 window 的 {n_win} —— "
        f"有效深度 >= D 的話不應該發生")


def test_batch_effective_depth_is_not_uniform_d():
    """batch **不是** uniform depth D —— 它與 window 必須真的不同。

    這條是防呆：如果 batch 不小心被實作成 window（例如批次長度算錯變成 1），
    上面兩條都會通過（不一致率 0、BER 相同），但那時 B2 量到的功耗
    就不是記憶體式回溯的功耗。深度小的時候差異才看得出來，所以取 D=32、低 SNR。
    """
    _, win, bat = _run(32, 2.0, B=400)
    assert not np.array_equal(win, bat), (
        "batch 與 window 解出完全相同的位元 —— batch 可能被實作成 uniform depth D，"
        "那樣 B2 量到的就不是記憶體式回溯")


def test_batch_rejects_unknown_mode():
    """未知的 mode 必須拋錯，不能靜靜當成 window。"""
    t = viterbi_trellis()
    rq = np.zeros((1, N_INFO + t.m, 2), dtype=np.int64)
    with pytest.raises(ValueError):
        decode_fx(rq, t, Q, W, 32, N_INFO, mode="nonsense", check_g6=False)
