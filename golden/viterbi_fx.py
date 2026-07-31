"""viterbi_fx.py — L2：定點 golden model。**這是本專案的參考基準（reference of record）。**

RTL 必須與這支檔案在每一個 trellis stage 的 `bm` / `pm` / `survivor` / 解碼位元上
**逐位元相等**（C2 / G5，零容忍）。

## 兩組 path metric（G6 的核心設計）

    pm_mod   uint，mod 2^W    <- C2 的比對標的（RTL 存的就是這個）
    pm_ref   int64，無界      <- G6 的參考

每個 stage 斷言「由 pm_mod 導出的 ACS 選擇與 argmin」等於「由 pm_ref 導出的」。
**這才是 modulo normalization 正確性的證明**，而不只是 spread 不等式。

為什麼不只查 spread：`|PM_i − PM_j| < 2^(W−1)` 是**充分條件**，不是必要條件。
實際的 spread 通常遠小於最壞界（尤其高 SNR），所以某個「先驗不安全」的格點
未必真的會 wrap。真正要問的是「wrap 有沒有讓某個決策翻掉」——那才是會壞事的東西。

## Modulo 比較

    diff  = (sum_b − sum_a) mod 2^W
    sel_a = signed_W(diff) >= 0

減法方向刻意是 b−a：平手（diff == 0）時 `sel_a` 為真，自動落到 A（survivor bit 0），
**不需要額外的等於比較器**。這與 docs/trellis_convention.md §4 的凍結慣例一致。
"""

import numpy as np

from .quantizer import lambda_max, pm_init
from .traceback import traceback


def _signed(x, W):
    """把 W-bit 無號值解讀為 W-bit 二補數有號值。"""
    half = 1 << (W - 1)
    return (x + half) % (1 << W) - half


def argmin_modulo(pm_mod, W):
    """在 modulo 算術下取 PM 最小的狀態。

    **不能直接對 wrapped 的 pm_mod 取 argmin**——它們會 wrap，argmin 會挑到錯的狀態。
    正確做法：以狀態 0 為參考點相減，把差值解讀為 W-bit 有號數，再取最小。
    合法性由 G6 保證（|spread| < 2^(W−1)）。
    """
    d = _signed(pm_mod - pm_mod[:, [0]], W)
    return np.argmin(d, axis=1)          # np.argmin 平手取最低索引 —— 與凍結慣例一致


def decode_fx(rq, trellis, Q, W, D, n_info, mode="window",
              check_g6=True, keep_history=True):
    """定點 Viterbi。

    rq           : (B, T, 2) int —— 量化後的無號軟值，值域 [0, 2^Q − 1]
    Q            : 軟值位元數
    W            : path metric 字寬
    D            : 回溯深度
    mode         : 'window' | 'ml'
    check_g6     : 是否維護無界參考 pm_ref 並比對決策（G6）
    keep_history : 是否保留每 stage 的 bm / pm（C2 比對需要；純量 BER 不需要）

    keep_history 預設為 True（C2 是本檔存在的理由），但量 BER 時必須關掉：
    pm 的歷史是 (B, T, 64) 的 int64，B=400 / T=1030 時就是 211 MB —— 開 14 個平行
    process 會直接吃掉 3 GB。BER 只需要 dec，不需要歷史。

    回傳 dict：
        dec       (B, n_info) uint8   解碼後的資訊位元
        bm        (B, T, 4)   int     每 stage 的 branch metric 向量（C2 比對用）
        pm        (B, T, S)   int     每 stage 結束後的 pm_mod（C2 比對用）
        surv      (B, T, S)   uint8   survivor bits（C2 比對用）
        g6_ok     bool                所有 stage 的決策都與無界參考一致
        g6_first  int                 第一個決策不一致的 stage（沒有則為 -1）
        spread    (B, T)      int     每 stage 的實際 PM spread（由 pm_ref 量）
    """
    rq = np.asarray(rq, dtype=np.int64)
    B, T, n_out = rq.shape
    assert n_out == 2
    assert T == n_info + trellis.m

    S = trellis.n_states
    H = trellis.half
    j = np.arange(trellis.n_bfly)
    X = trellis.bfly_out[j]

    lam = lambda_max(Q)
    maxr = (1 << Q) - 1
    mask = (1 << W) - 1
    P0 = pm_init(Q)

    # pm_mod 存的是「已經 mod 2^W 化簡的值」——RTL 存的就是這個。
    # 注意 P0 未必放得下 W bits（例如 Q=6 時 P0=757，W=8 只能存到 255），
    # 那就是會 wrap ——這正是不安全格點的定義，不是 bug。
    pm_mod = np.full((B, S), P0 & mask, dtype=np.int64)
    pm_mod[:, 0] = 0

    pm_ref = None
    spread = None
    if check_g6:
        pm_ref = np.full((B, S), P0, dtype=np.int64)
        pm_ref[:, 0] = 0
        spread = np.zeros((B, T), dtype=np.int64)

    bm_hist = np.zeros((B, T, 4), dtype=np.int64) if keep_history else None
    pm_hist = np.zeros((B, T, S), dtype=np.int64) if keep_history else None
    surv = np.zeros((B, T, S), dtype=np.uint8)      # traceback 一定要用，不能省
    best = np.zeros((B, T), dtype=np.int64)

    g6_first = -1

    for t in range(T):
        r0 = rq[:, t, 0]
        r1 = rq[:, t, 1]

        # branch metric 向量：bm[c] = bm(c0) + bm(c1)，c = (c0<<1)|c1
        #   bm(0) = r，bm(1) = (2^Q − 1) − r      —— 非負距離度量
        bm = np.empty((B, 4), dtype=np.int64)
        for c in range(4):
            b0 = r0 if ((c >> 1) & 1) == 0 else (maxr - r0)
            b1 = r1 if (c & 1) == 0 else (maxr - r1)
            bm[:, c] = b0 + b1
        if keep_history:
            bm_hist[:, t, :] = bm

        bm_X = bm[:, X]                 # (B, 32)
        bm_Xc = lam - bm_X              # bm[~X] = λ_max − bm[X]（互補性）

        # ---- modulo 算術（RTL 做的事）----
        pa = pm_mod[:, j]
        pb = pm_mod[:, j + H]

        a0 = (pa + bm_X) & mask
        b0 = (pb + bm_Xc) & mask
        d0 = (b0 - a0) & mask
        sel0 = ((d0 >> (W - 1)) & 1) == 0      # signed(b−a) >= 0 -> 選 A（含平手）

        a1 = (pa + bm_Xc) & mask
        b1 = (pb + bm_X) & mask
        d1 = (b1 - a1) & mask
        sel1 = ((d1 >> (W - 1)) & 1) == 0

        pm_new = np.empty_like(pm_mod)
        pm_new[:, 0::2] = np.where(sel0, a0, b0)
        pm_new[:, 1::2] = np.where(sel1, a1, b1)
        surv[:, t, 0::2] = np.where(sel0, 0, 1)
        surv[:, t, 1::2] = np.where(sel1, 0, 1)

        pm_mod = pm_new
        if keep_history:
            pm_hist[:, t, :] = pm_mod

        best[:, t] = argmin_modulo(pm_mod, W)

        # ---- 無界參考算術（G6 的對照）----
        if check_g6:
            ra = pm_ref[:, j]
            rb = pm_ref[:, j + H]
            ra0 = ra + bm_X
            rb0 = rb + bm_Xc
            rsel0 = ra0 <= rb0                 # 平手選 A —— 與 modulo 版同一慣例
            ra1 = ra + bm_Xc
            rb1 = rb + bm_X
            rsel1 = ra1 <= rb1

            pr_new = np.empty_like(pm_ref)
            pr_new[:, 0::2] = np.where(rsel0, ra0, rb0)
            pr_new[:, 1::2] = np.where(rsel1, ra1, rb1)
            pm_ref = pr_new

            # 實際 spread（由無界參考量）：「實測 Δ_max vs 最壞界」那張圖的資料
            spread[:, t] = pm_ref.max(axis=1) - pm_ref.min(axis=1)

            if g6_first < 0:
                same_acs = (np.array_equal(sel0, rsel0)
                            and np.array_equal(sel1, rsel1))
                # argmin 也要一致：wrap 可能沒讓 ACS 翻掉，卻讓 min-PM 狀態挑錯。
                same_min = np.array_equal(best[:, t], np.argmin(pm_ref, axis=1))
                if not (same_acs and same_min):
                    g6_first = t

    dec = traceback(surv, best, D, n_info, trellis.m, mode=mode)

    return {
        "dec": dec,
        "bm": bm_hist,
        "pm": pm_hist,
        "surv": surv,
        "best": best,
        "g6_ok": g6_first < 0,
        "g6_first": g6_first,
        "spread": spread,
    }
