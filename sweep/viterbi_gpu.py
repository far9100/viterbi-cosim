"""viterbi_gpu.py — L2 的 GPU 版：torch 整數運算，跨 frame 完全平行。

## 這支檔案的定位

它**不是**一個新的參考基準。參考基準只有一個：`golden/viterbi_fx.py`。
這支檔案存在的唯一理由是速度——設計空間有 ~640 個 (組態 x SNR) 點要掃，
CPU 上的 golden 只跑 ~490 kb/s。

因此它必須與 CPU golden **逐位元相等**，由 `sweep/test_c2prime.py`（C2′ 閘門）證明。
規格書 v1 沒有這個比對點，是計畫審查時補上的。

## 為什麼 C2′ 非有不可

`torch.minimum` 是逐元素運算，**不回傳索引**——survivor bit 得自己算。於是：

    sel_a = (sum_a <= sum_b)      # 對：平手選 A
    sel_a = (sum_a <  sum_b)      # 錯：平手選 B

兩者都能跑，都不會報錯。Q=3 時軟值只有 8 階，**整數平手非常常見**。
選錯方向的後果是：GPU 掃出來的 BER 與 CPU golden 對不起來，
而且要等到 M3 的 RTL 上線、C2 開始噴 mismatch，才會發現是掃描這一側錯了。

同理，`torch.argmin` 的**平手行為在文件上沒有保證**（numpy 的 argmin 有保證回傳第一個）。
所以這裡不用 argmin 的隱含行為，改用一個顯式的鍵：

    key  = d * 64 + state_index
    best = argmin(key)

d 是以狀態 0 為參考、解讀成 W-bit 有號數的 path metric 差（|d| < 2^11 = 2048），
乘上 64 再加索引，字典序就等於 (d, index) 的字典序——平手時必定取到最低索引。
不依賴任何函式庫的未定義行為。

## 為什麼用 int32

所有中間值都放得下 int32：pm < 2^12，bm < 2^7，key < 2^17。
int64 在 GPU 上明顯較慢，而且沒有換到任何東西。
（溢位風險已由上面的界排除；C2′ 會把這件事釘死。）
"""

import numpy as np
import torch


def _signed_t(x, W):
    """把 W-bit 無號值解讀為 W-bit 二補數有號值（torch 版）。"""
    half = 1 << (W - 1)
    full = 1 << W
    return ((x + half) % full) - half


def argmin_modulo_t(pm, W):
    """modulo 算術下的 min-PM 狀態。平手取最低索引（顯式，不靠 argmin 的未定義行為）。"""
    d = _signed_t(pm - pm[:, 0:1], W)                     # (B, 64)
    idx = torch.arange(pm.shape[1], device=pm.device, dtype=pm.dtype)
    key = d * pm.shape[1] + idx                           # 字典序 = (d, index)
    return torch.argmin(key, dim=1)


def decode_gpu(rq, trellis, Q, W, D, n_info, device="cuda",
               mode="window", want_history=False):
    """定點 Viterbi 的 GPU 版。與 golden/viterbi_fx.decode_fx 逐行對應。

    rq : (B, T, 2) 量化後的無號軟值，值域 [0, 2^Q − 1]（numpy 或 torch 皆可）

    回傳 dict：dec；want_history 為真時另含 pm / surv / best（C2′ 比對用）。
    """
    dev = torch.device(device)
    if not torch.is_tensor(rq):
        rq = torch.from_numpy(np.asarray(rq, dtype=np.int32))
    rq = rq.to(dev, torch.int32)

    B, T, n_out = rq.shape
    assert n_out == 2 and T == n_info + trellis.m

    S = trellis.n_states                 # 64
    H = trellis.half                     # 32
    NB = trellis.n_bfly                  # 32
    m_bit = trellis.m - 1                # 5

    X = torch.as_tensor(trellis.bfly_out, device=dev, dtype=torch.long)   # (32,)
    Xc = X ^ ((1 << n_out) - 1)

    lam = 2 * ((1 << Q) - 1)
    maxr = (1 << Q) - 1
    mask = (1 << W) - 1
    P0 = 6 * lam + 1

    # pm_mod：已 mod 2^W 化簡的值（RTL 存的就是這個）。P0 未必放得下 W bits——
    # 那正是「不安全格點」的定義，不是 bug。
    pm = torch.full((B, S), P0 & mask, device=dev, dtype=torch.int32)
    pm[:, 0] = 0

    # survivor 以**位元打包**存成兩個 (B, T) 的 int32：lo = 狀態 0..31，hi = 狀態 32..63。
    #
    # 三個版本都實測過（scripts/bench_gpu.py）：
    #
    #   (B, T, 64) uint8 + 隨機 gather   B=16384: 2042 MB, 38.5 Mb/s
    #   (B, T) int64 打包                B=16384:  732 MB,  7.6 Mb/s   <- 慘敗
    #   (B, T) int32 x2 打包             B=32768: 1462 MB, 31.0 Mb/s   <- 採用
    #
    # int64 版是個教訓：**消費級 GeForce 的 int64 整數運算不是全速率**，
    # 把整個 traceback 換成 int64 讓吞吐掉了 5 倍。改成兩個 int32 就好了。
    #
    # 最終選 int32 打包而不是 uint8 gather，理由是**記憶體**：打包版在同樣的
    # 記憶體預算下能開更大的 B（gather 版 B=16384 就要 2 GB），而 B 越大，
    # 每個 batch 固定的 ~26k 次 kernel launch 就攤得越薄。
    # 兩者的吞吐在各自的最佳 B 下相當，但打包版還有往上開的空間。
    lo = torch.zeros((B, T), device=dev, dtype=torch.int32)
    hi = torch.zeros((B, T), device=dev, dtype=torch.int32)
    best = torch.zeros((B, T), device=dev, dtype=torch.int32)
    pm_hist = (torch.zeros((B, T, S), device=dev, dtype=torch.int32)
               if want_history else None)
    surv = (torch.zeros((B, T, S), device=dev, dtype=torch.uint8)
            if want_history else None)

    # 狀態 2j 在 bit 2j、狀態 2j+1 在 bit 2j+1。前 16 個 butterfly 落在 lo，後 16 個落在 hi。
    sh_e = (2 * torch.arange(NB, device=dev, dtype=torch.int32))        # 0,2,...,62
    sh_o = sh_e + 1                                                     # 1,3,...,63
    half_bf = NB // 2                                                   # 16

    # bm[c] = bm(c0) + bm(c1)，c = (c0<<1)|c1 -> c0 = [0,0,1,1], c1 = [0,1,0,1]
    c0_is_one = torch.as_tensor([0, 0, 1, 1], device=dev, dtype=torch.int32)
    c1_is_one = torch.as_tensor([0, 1, 0, 1], device=dev, dtype=torch.int32)

    for t in range(T):
        r0 = rq[:, t, 0:1]                                    # (B,1)
        r1 = rq[:, t, 1:2]
        # bm(0) = r，bm(1) = maxr − r  —— 非負距離度量
        b0 = torch.where(c0_is_one.bool(), maxr - r0, r0)     # (B,4)
        b1 = torch.where(c1_is_one.bool(), maxr - r1, r1)
        bm = b0 + b1                                          # (B,4)

        bm_X = bm[:, X]                                       # (B,32)
        bm_Xc = lam - bm_X                                    # 互補性：bm[~X] = λ_max − bm[X]

        pa = pm[:, :H]                                        # PM[j]
        pb = pm[:, H:]                                        # PM[j+32]

        # 進入 2j（u=0）：前驅 j 的碼字是 X，前驅 j+32 的是 ~X
        a0 = (pa + bm_X) & mask
        q0 = (pb + bm_Xc) & mask
        d0 = (q0 - a0) & mask
        sel0 = ((d0 >> (W - 1)) & 1) == 0     # signed(b−a) >= 0 -> 選 A（**含平手**）

        # 進入 2j+1（u=1）：前驅 j 的碼字是 ~X，前驅 j+32 的是 X
        a1 = (pa + bm_Xc) & mask
        q1 = (pb + bm_X) & mask
        d1 = (q1 - a1) & mask
        sel1 = ((d1 >> (W - 1)) & 1) == 0

        pm_even = torch.where(sel0, a0, q0)                   # 狀態 2j
        pm_odd = torch.where(sel1, a1, q1)                    # 狀態 2j+1
        pm = torch.stack((pm_even, pm_odd), dim=2).reshape(B, S)

        s_even = (~sel0).to(torch.int32)                      # (B,32) 狀態 2j
        s_odd = (~sel1).to(torch.int32)                       # (B,32) 狀態 2j+1

        # 位元打包。各位元互不重疊，所以「相加」等價於 bitwise OR（不會有進位）。
        # butterfly 0..15 -> 狀態 0..31 -> lo；butterfly 16..31 -> 狀態 32..63 -> hi。
        lo[:, t] = ((s_even[:, :half_bf] << sh_e[:half_bf]).sum(dim=1)
                    + (s_odd[:, :half_bf] << sh_o[:half_bf]).sum(dim=1))
        hi[:, t] = ((s_even[:, half_bf:] << (sh_e[half_bf:] - 32)).sum(dim=1)
                    + (s_odd[:, half_bf:] << (sh_o[half_bf:] - 32)).sum(dim=1))

        best[:, t] = argmin_modulo_t(pm, W).to(torch.int32)
        if want_history:
            pm_hist[:, t, :] = pm
            surv[:, t, :] = torch.stack(
                (s_even.to(torch.uint8), s_odd.to(torch.uint8)), dim=2).reshape(B, S)

    dec = _traceback_gpu(lo, hi, best, D, n_info, m_bit, mode)

    out = {"dec": dec}
    if want_history:
        out["pm"] = pm_hist
        out["surv"] = surv
        out["best"] = best
    return out


def _bit_of(lo, hi, s):
    """取狀態 s 的 survivor bit。lo 存狀態 0..31，hi 存狀態 32..63。

    兩邊都算再用 where 選——GPU 上分支發散比多做一次移位貴，而且 int32 移位是全速率的。
    """
    b_lo = (lo >> (s & 31)) & 1
    b_hi = (hi >> (s & 31)) & 1
    return torch.where(s < 32, b_lo, b_hi)


def _traceback_gpu(lo, hi, best, D, n_info, m_bit, mode):
    """與 golden/traceback.py 同一組語意（docs/traceback_convention.md）。

    lo / hi: (B, T) int32，survivor bits 打包成兩個 32-bit 字。

    因為 survivor 是打包的，取某個 stage 的 survivor 只要對 lo/hi 做一次**切片**
    （連續記憶體）再逐元素取位元——不需要 gather。
    """
    B, T = lo.shape
    dev = lo.device
    dec = torch.zeros((B, T), device=dev, dtype=torch.uint8)

    if mode == "ml":
        s = torch.zeros(B, device=dev, dtype=torch.int32)
        for t in range(T - 1, -1, -1):
            dec[:, t] = (s & 1).to(torch.uint8)
            sv = _bit_of(lo[:, t], hi[:, t], s)
            s = (s >> 1) | (sv << m_bit)
        return dec[:, :n_info]

    # 主體：所有 t 一起往回追，一次一步。
    # 第 k 步要的是 stage (starts - k) 的 survivor —— lo/hi 的一段連續切片。
    s = best[:, (D - 1):T].clone()                  # (B, Nt) int32 = s_{t+1}
    for k in range(D - 1):
        sv = _bit_of(lo[:, (D - 1 - k):(T - k)],
                     hi[:, (D - 1 - k):(T - k)], s)
        s = (s >> 1) | (sv << m_bit)
    dec[:, 0:(T - D + 1)] = (s & 1).to(torch.uint8)

    # 尾端：利用 termination 從狀態 0 沖出剩下的 D−1 個位元
    s1 = torch.zeros(B, device=dev, dtype=torch.int32)
    for t in range(T - 1, T - D, -1):
        dec[:, t] = (s1 & 1).to(torch.uint8)
        sv = _bit_of(lo[:, t], hi[:, t], s1)
        s1 = (s1 >> 1) | (sv << m_bit)

    return dec[:, :n_info]
