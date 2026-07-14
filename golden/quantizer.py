"""quantizer.py — LLR 均勻量化器（Q, clip 參數化）。

## 語意（凍結）

以雜訊標準差 σ 為單位設定 clip level A = clip · σ（假設完美 AGC，即接收機知道 σ；
這是「3-bit 軟判決損失 0.2 dB」這個經典結果的前提）。

    r = clip_to_range( round( (A − y) · (2^Q − 1) / (2A) ),  0,  2^Q − 1 )

**r 隨 y 遞減**：

    y = +A  ->  r = 0            （強烈傾向碼位元 0；BPSK 的 0 -> +1）
    y =  0  ->  r = (2^Q−1)/2
    y = −A  ->  r = 2^Q − 1      （強烈傾向碼位元 1）

這個方向是刻意的，因為 branch metric 是**距離**（越小越好）：

    bm(c=0) = r              y 很正（像 0）時 r 小 -> 假設 c=0 的代價低   [對]
    bm(c=1) = (2^Q−1) − r    y 很正時這個大 -> 假設 c=1 的代價高          [對]

## 為什麼這與最大似然一致

BPSK over AWGN 的 ML 度量是最小化 Σ (y − x)²，等價於最大化相關度 Σ y·x（x = 1−2c）。
寫成要最小化的代價就是 −y·x：c=0 時是 −y，c=1 時是 +y。

而本量化器的 bm（把 clip 與 round 拿掉、看連續版本）是

    bm(c=0) ∝ (A − y) = −y + A
    bm(c=1) ∝ (A + y) = +y + A

也就是 **bm(c) = k·(−y·x) + kA**：與 ML 代價只差一個正的比例常數與一個**每符號的常數**。
常數在 ACS 的比較中抵銷，比例常數不改變 argmin。**所以決策與 ML 相同。**

C1（量化損失）量的就是「clip + round + 有限 D + modulo W」這四件事加起來的 dB 代價。
"""

import numpy as np


def quantize(y, sigma, Q, clip):
    """把接收到的軟值量化成 Q-bit 無號整數。

    y     : 接收軟值（任意 shape）
    sigma : 該工作點的雜訊標準差（每實數維度）
    Q     : 位元數，量化階數 = 2^Q
    clip  : clip level，以 σ 為單位（例如 2.0 表示 A = 2σ）

    回傳與 y 同 shape 的整數陣列，值域 [0, 2^Q − 1]。
    """
    y = np.asarray(y, dtype=np.float64)
    levels = (1 << Q) - 1          # 2^Q − 1
    A = clip * sigma

    # (A − y) / (2A) 把 [−A, +A] 線性映到 [1, 0]，再乘上 levels
    r = np.round((A - y) * levels / (2.0 * A))
    return np.clip(r, 0, levels).astype(np.int64)


def sigma_from_ebn0(ebn0_db, R, bits_per_symbol=1):
    """由 Eb/N0 算出每實數維度的雜訊標準差。

    與既有通訊模擬器 commsim/channel.py 的 awgn() 完全一致（Es 正規化為 1）：
        Es/N0 = Eb/N0 · R · m
        N0    = 1 / (Es/N0)
        sigma = sqrt(N0 / 2)

    一致性很重要：golden model 的量化器必須看到與通道注入時**同一個** σ，
    否則 clip level 就不是它宣稱的那個 σ 倍數，G3 的 0.2 dB 也就無從談起。
    """
    ebn0_lin = 10.0 ** (np.asarray(ebn0_db, dtype=np.float64) / 10.0)
    esn0_lin = ebn0_lin * R * bits_per_symbol
    N0 = 1.0 / esn0_lin
    return np.sqrt(N0 / 2.0)


def lambda_max(Q):
    """一個 rate-1/2 分支的 branch metric 上界： λ_max = 2·(2^Q − 1)。"""
    return 2 * ((1 << Q) - 1)


def pm_init(Q):
    """假起始狀態的懲罰值： PM_INIT = 6·λ_max + 1（見 docs/wordlength_bound.md §2）。"""
    return 6 * lambda_max(Q) + 1


def w_is_safe(Q, W):
    """G6 的先驗安全條件： 2^(W−1) > 14·(2^Q − 1) + 1。"""
    return (1 << (W - 1)) > 14 * ((1 << Q) - 1) + 1
