"""bounds.py — 卷積碼的重量分布與 union bound（G2a 的 oracle）。

## 為什麼 G2a 是一道「真的」閘門

規格書 v1 的 G2 是「增益 ≈ 5 dB ±0.3」——那個 ±0.3 是拍腦袋來的，而且（見
docs/falsification.md）期望值本身就偏低了 0.3–0.4 dB。與其去調容差，不如換一個
**可證明**的判準：

    union bound 是 BER 的嚴格上界。實測 BER 若高於它，一定是有東西壞了。

這不是容差，是定理。零容忍。

## 重量分布：算出來的，不是抄來的

c_d（輸出重量為 d 的所有路徑的「輸入重量」總和）用廣度優先枚舉算，不從文獻抄。
理由：抄來的表若與實際的多項式對不起來（打錯一個八進位字），G2a 就會拿一個
錯誤的上界去驗證一個錯誤的解碼器，而且很可能「通過」。自己算就不會有這個縫。

算完之後與文獻值對照（(133,171)：a_10=11, a_12=38, a_14=193；c_10=36, c_12=211,
c_14=1404）當作 sanity check。

## Union bound

    P_b  <=  Σ_{d>=dfree}  c_d · Q( sqrt( 2 · d · Es/N0 ) )

其中 Es/N0 是**通道實際交付的**每碼符號訊噪比：Es/N0 = (Eb/N0) · R_terminated。
用終止碼率而不是名目的 1/2，是因為 tail bits 真的花了發射能量——這與
commsim/channel.py 的 awgn() 對 R 的處理一致。
"""

import math

import numpy as np


def weight_spectrum(trellis, d_max=24):
    """枚舉所有「離開狀態 0、再回到狀態 0」的路徑，回傳 (a_d, c_d)。

    a_d = 輸出重量為 d 的路徑數
    c_d = 那些路徑的輸入重量總和（union bound 用的是這個）

    做法是對 (state, 輸出重量, 輸入重量) 做動態規劃。輸出重量超過 d_max 的路徑剪掉。
    """
    S = trellis.n_states
    a = np.zeros(d_max + 1, dtype=np.int64)
    c = np.zeros(d_max + 1, dtype=np.int64)

    # live[(s, d, i)] = 路徑數。第一步必須是 u=1（否則沒離開全零路徑）
    live = {}
    ns = int(trellis.next_state[0, 1])
    w = bin(int(trellis.out[0, 1])).count("1")
    live[(ns, w, 1)] = 1

    # 每一輪把所有活著的路徑往前推一步。輸出重量單調不減，所以 d_max 是有效的終止條件。
    for _ in range(d_max * trellis.n_out + 2):
        nxt = {}
        for (s, d, i), cnt in live.items():
            for u in (0, 1):
                nd = d + bin(int(trellis.out[s, u])).count("1")
                if nd > d_max:
                    continue
                ni = i + u
                nstate = int(trellis.next_state[s, u])
                if nstate == 0:
                    # 回到狀態 0：這是一個完整的 error event
                    a[nd] += cnt
                    c[nd] += cnt * ni
                else:
                    key = (nstate, nd, ni)
                    nxt[key] = nxt.get(key, 0) + cnt
        if not nxt:
            break
        live = nxt

    return a, c


def q_function(x):
    """Q(x) = 0.5 · erfc(x / sqrt(2))。用標準庫的 erfc，不引入 scipy。"""
    return 0.5 * np.vectorize(math.erfc)(np.asarray(x, dtype=np.float64) / math.sqrt(2.0))


def union_bound_ber(ebn0_db, c_spectrum, R, d_free):
    """**軟判決** Viterbi 的 BER union bound。

    ebn0_db     : 純量或陣列
    c_spectrum  : weight_spectrum() 回傳的 c_d
    R           : 終止碼率（通道實際用的那個）
    """
    ebn0_lin = 10.0 ** (np.asarray(ebn0_db, dtype=np.float64) / 10.0)
    esn0 = ebn0_lin * R                      # BPSK：m = 1
    total = np.zeros_like(esn0, dtype=np.float64)
    for d in range(d_free, len(c_spectrum)):
        if c_spectrum[d] == 0:
            continue
        total = total + c_spectrum[d] * q_function(np.sqrt(2.0 * d * esn0))
    return total


def _pairwise_hard(d, p):
    """硬判決下，兩條相距 d 的路徑選錯的機率（BSC 的錯誤機率為 p）。

    d 為奇數：錯超過一半就選錯 -> k > d/2
    d 為偶數：剛好一半時平手，以 1/2 的機率選錯
    """
    d = int(d)
    p = np.asarray(p, dtype=np.float64)
    total = np.zeros_like(p)
    for k in range((d // 2) + 1, d + 1):
        total = total + math.comb(d, k) * p ** k * (1.0 - p) ** (d - k)
    if d % 2 == 0:
        h = d // 2
        total = total + 0.5 * math.comb(d, h) * p ** h * (1.0 - p) ** h
    return total


def union_bound_ber_hard(ebn0_db, c_spectrum, R, d_free):
    """**硬判決** Viterbi 的 BER union bound。

    存在的理由：規格書 G4 的「硬判決 vs 軟判決損失 ≈ 2 dB」是一條**經驗法則**，
    不是這個碼在這個 BER 下的精確值。實測（M1）給出約 2.5 dB，落在 ±0.3 之外。

    要判斷「2.5 dB 到底是解碼器壞了，還是那條經驗法則本來就不準」，需要一個
    可推導的參考——就是這個界。理論上，硬判決的漸近指數只有軟判決的一半
    （P_d ~ (4p(1-p))^(d/2)），所以漸近損失是 10·log10(2) = 3 dB；
    在 1e-5 這種非漸近的區域，落在 2~3 dB 之間才是預期的。
    """
    ebn0_lin = 10.0 ** (np.asarray(ebn0_db, dtype=np.float64) / 10.0)
    esn0 = ebn0_lin * R
    p = q_function(np.sqrt(2.0 * esn0))      # BSC 的交越機率
    total = np.zeros_like(esn0, dtype=np.float64)
    for d in range(d_free, len(c_spectrum)):
        if c_spectrum[d] == 0:
            continue
        total = total + c_spectrum[d] * _pairwise_hard(d, p)
    return total
