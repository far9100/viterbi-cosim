"""stimulus.py — 在 GPU 上產生激勵（資訊位元 -> 編碼 -> BPSK -> AWGN -> 量化）。

## 為什麼要搬到 GPU

第一版把激勵留在 CPU：每個 batch 要 numpy 產生 3370 萬個高斯亂數（270 MB），
再跑一個 1030 次迭代的 Python 編碼迴圈。結果是 **GPU 在空轉**——
解碼只花 0.44 秒，CPU 端的準備卻要 2 秒以上，整體只有 6.7 Mb/s，
遠低於解碼器本身的 38.5 Mb/s。

## 編碼器的向量化（把 1030 次迭代變成一次）

狀態的定義是 `s_t 的 bit k = u_{t-1-k}`——也就是**最近 6 個輸入位元的打包**。
所以整條狀態序列可以用「移位視窗」一次算完，根本不需要迴圈：

    u_pad = [0]*6 ++ u                       # 前面補 6 個零（編碼器由狀態 0 起始）
    s_t   = Σ_{k=0..5}  u_pad[t+5-k] << k

寫成張量就是 6 次 slice + shift + add。之後碼字是一次 gather：`out_table[s, u]`。

## 亂數

用 torch 的 CUDA 產生器（給定 seed 後是確定的），不是 numpy 的。
兩者的串流不同，但這無所謂：BER 只要求「統計上是對的 AWGN」+「seed 有記錄」。
**逐位元組的可重現性靠的是 seed，而 M4 的 Tier B 激勵則會直接凍結位元組 + SHA-256。**

C2′ 已經證明**解碼器**與 CPU golden 逐位元相等；本檔的編碼器另外由
`test_c2prime.py::test_gpu_encoder_matches_cpu` 驗證。激勵的「資料」與解碼的「邏輯」
是兩件事，分別驗證。
"""

import numpy as np
import torch


class GpuStimulus:
    """把 trellis 表搬上 GPU，之後每個 batch 都不再回 CPU。"""

    def __init__(self, trellis, device="cuda"):
        self.t = trellis
        self.dev = torch.device(device)
        self.next = torch.as_tensor(trellis.next_state, device=self.dev,
                                    dtype=torch.long)          # (64, 2)
        self.out = torch.as_tensor(trellis.out, device=self.dev,
                                   dtype=torch.long)           # (64, 2)
        self.m = trellis.m

    def encode(self, info):
        """info: (B, L) int64 tensor of 0/1 -> 碼字 (B, L+m, 2) int64。

        終止式：尾端補 m 個零，把編碼器逼回狀態 0。
        """
        B, L = info.shape
        m = self.m
        T = L + m
        padded = torch.cat(
            [info, torch.zeros((B, m), device=self.dev, dtype=torch.long)], dim=1)

        # s_t 的 bit k = u_{t-1-k}：前面補 m 個零，再用移位視窗一次算完整條狀態序列
        u_pad = torch.cat(
            [torch.zeros((B, m), device=self.dev, dtype=torch.long), padded], dim=1)
        s = torch.zeros((B, T), device=self.dev, dtype=torch.long)
        for k in range(m):
            s |= u_pad[:, (m - 1 - k):(m - 1 - k + T)] << k

        val = self.out[s, padded]                              # (B, T)
        c0 = (val >> 1) & 1
        c1 = val & 1
        return torch.stack((c0, c1), dim=2)                    # (B, T, 2)

    def make(self, B, n_info, snr_db, Q, clip, R, generator):
        """一個 batch 的激勵。回傳 (info, rq)，兩者都在 GPU 上。"""
        info = torch.randint(0, 2, (B, n_info), device=self.dev,
                             dtype=torch.long, generator=generator)
        cw = self.encode(info)

        # BPSK：0 -> +1, 1 -> -1（與 commsim.modulation.bpsk_modulate 一致）
        x = 1.0 - 2.0 * cw.to(torch.float32)

        ebn0 = 10.0 ** (snr_db / 10.0)
        sigma = float(np.sqrt(1.0 / (2.0 * ebn0 * R)))          # = sqrt(N0/2), Es=1
        rx = x + sigma * torch.randn(x.shape, device=self.dev,
                                     dtype=torch.float32, generator=generator)

        # 均勻量化器：r 隨 y 遞減（見 golden/quantizer.py）
        levels = (1 << Q) - 1
        A = clip * sigma
        r = torch.round((A - rx) * levels / (2.0 * A))
        rq = torch.clamp(r, 0, levels).to(torch.int32)

        return info, rq
