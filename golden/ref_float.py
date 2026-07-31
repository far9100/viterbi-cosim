"""ref_float.py — L1：K=7 (133,171) 的**浮點**參考解碼器。

## 為什麼這支檔案必須新寫

規格書 v1 說「L1 = 既有 numpy 鏈路」。實測後不成立：既有的通訊模擬器裡只有
**K=3 (7,5)、4 狀態、硬編碼 trellis** 的 Viterbi（`commsim/coding.py` 的 `_viterbi_core`，
branch metric 的簽名是 `(c1, c2, o1, o2)`——字面上就是兩個輸出位元）。
K=7 是重寫，不是換參數。

## 從既有模擬器複用的部分

只複用它**真正有的**東西，不硬凹：

- `commsim.channel.awgn`        —— Eb/N0 參數化、含碼率因子 R 的 AWGN
- `commsim.modulation.bpsk_modulate`
- `commsim.theory.bpsk_ber_theory` —— Q 函數閉式解（G1 的 oracle）
- `commsim.metrics.*`           —— Wilson / cluster-robust CI、required_ebn0、coding_gain

其中 `cluster_robust_ci` 特別重要：Viterbi 一旦出錯就會噴出一串相鄰的位元錯誤，
Wilson 區間假設位元獨立，會低估變異。既有模擬器已經實測校準過這件事
（卷積軟判決的 var_inflation ≈ 2.03）。這是現成的、對的東西。

## 度量的選擇

用**平方歐氏距離** `Σ (y − x)²`（x = 1 − 2c）。AWGN 下最小化它就是 ML。
刻意選它而不是相關度量，是為了與既有模擬器的 `conv_decode_soft` 逐項相同，
讓 K=3 的 oracle 測試不只是「解出來一樣」，連 path metric 的數值都一樣。
"""

import os
import sys

import numpy as np

from .traceback import traceback

# 既有通訊模擬器：不是可安裝的套件（pyproject.toml 只有 [tool.mutmut]，沒有 [project]），
# 且路徑含空白字元。只能用 sys.path 注入。
# 路徑不再寫死在這裡。scripts/check_commsim.py 是唯一的定位器，
# 它同時負責用 third_party/commsim.lock 驗內容 —— M1/M2 的每個 BER 點都由
# commsim 產生雜訊，內容變了已發表的數字就不再可重現。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.check_commsim import locate as _locate_commsim  # noqa: E402

_COMMSIM = _locate_commsim()
if _COMMSIM and _COMMSIM not in sys.path:
    sys.path.insert(0, _COMMSIM)


def commsim():
    """延遲載入既有模擬器（讓 golden/ 在沒有它時仍可 import）。

    **找不到時在這裡失敗，不是在 import 時失敗。** 本模組的 `decode_float`
    根本不需要 commsim，而 `golden/ber.py` 又 import 本模組 —— 在 import 時就 raise
    會讓所有相依 `golden.ber` 的東西（含 C2′ 的 47 條與 union bound 的 9 條測試）
    整個無法收集，而它們一行都用不到 commsim。錯誤訊息留在真正需要它的地方。
    """
    if _COMMSIM is None:
        raise ImportError(
            "找不到 commsim（既有通訊模擬器）。M1/M2 的 BER 全部由它產生雜訊，"
            "沒有它一個數字都重生不出來。\n"
            "  設 COMMSIM_PATH，或 clone 到 third_party/commsim-src：\n"
            "    git clone git@github.com:far9100/communications-relay-simulator.git "
            "third_party/commsim-src")
    from commsim import channel, metrics, modulation, theory
    return channel, modulation, theory, metrics


def decode_float(rx, trellis, D, n_info, mode="window", metric="soft"):
    """浮點 Viterbi。

    rx     : (B, T, 2) float —— 通道輸出的軟值（未量化）
    metric : 'soft' = 平方歐氏距離（ML）；'hard' = Hamming 距離（硬判決）
    mode   : 'window' | 'ml'（見 docs/traceback_convention.md）

    回傳 (B, n_info) 的 uint8。
    """
    rx = np.asarray(rx, dtype=np.float64)
    B, T, n_out = rx.shape
    assert n_out == 2
    assert T == n_info + trellis.m

    S = trellis.n_states
    H = trellis.half                       # 32
    j = np.arange(trellis.n_bfly)          # 0..31
    X = trellis.bfly_out[j]                # c(j, 0)
    full = (1 << n_out) - 1                # 3
    Xc = X ^ full                          # ~c(j, 0)

    if metric == "hard":
        hard = (rx < 0).astype(np.float64)   # BPSK：y<0 -> bit 1

    pm = np.full((B, S), np.inf, dtype=np.float64)
    pm[:, 0] = 0.0                          # 編碼器由狀態 0 起始
    surv = np.zeros((B, T, S), dtype=np.uint8)
    best = np.zeros((B, T), dtype=np.int64)

    for t in range(T):
        # bm[:, c] = 假設碼字為 c 時的分支度量（c = (c0<<1)|c1）
        bm = np.empty((B, 4), dtype=np.float64)
        for c in range(4):
            c0 = (c >> 1) & 1
            c1 = c & 1
            if metric == "soft":
                x0 = 1.0 - 2.0 * c0
                x1 = 1.0 - 2.0 * c1
                bm[:, c] = (rx[:, t, 0] - x0) ** 2 + (rx[:, t, 1] - x1) ** 2
            else:
                # 這個 .astype(np.float64) 不是裝飾——numpy 對兩個 bool 陣列做 `+` 是
                # **邏輯 OR**，不是整數相加。少了它，Hamming 距離就只會是 0 或 1、
                # 永遠到不了 2，解碼器分不出「錯一個位元」與「錯兩個位元」，
                # 於是變成一個不是 ML 的解碼器——而且不會有任何錯誤訊息。
                # （這個 bug 真的發生過：短 frame 的暴力 ML 測試 10/10 通過，
                #   是既有模擬器的 K=3 oracle 在真實 frame 長度下抓到的。）
                bm[:, c] = ((hard[:, t, 0] != c0).astype(np.float64)
                            + (hard[:, t, 1] != c1).astype(np.float64))

        bm_X = bm[:, X]            # (B, 32)
        bm_Xc = bm[:, Xc]          # (B, 32)
        pa = pm[:, j]              # PM[j]
        pb = pm[:, j + H]          # PM[j+32]

        # 進入 2j（u=0）：前驅 j 的碼字是 X，前驅 j+32 的是 ~X
        a0 = pa + bm_X
        b0 = pb + bm_Xc
        sel0 = a0 <= b0            # 平手選 A（survivor bit 0）——與凍結慣例一致

        # 進入 2j+1（u=1）：前驅 j 的碼字是 ~X，前驅 j+32 的是 X
        a1 = pa + bm_Xc
        b1 = pb + bm_X
        sel1 = a1 <= b1

        pm_new = np.empty_like(pm)
        pm_new[:, 0::2] = np.where(sel0, a0, b0)
        pm_new[:, 1::2] = np.where(sel1, a1, b1)
        surv[:, t, 0::2] = np.where(sel0, 0, 1)
        surv[:, t, 1::2] = np.where(sel1, 0, 1)

        pm = pm_new
        best[:, t] = np.argmin(pm, axis=1)      # 浮點無 wraparound，直接 argmin

    return traceback(surv, best, D, n_info, trellis.m, mode=mode)
