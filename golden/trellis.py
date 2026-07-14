"""trellis.py — 卷積碼的 trellis 結構，由生成多項式推導。

本檔是 L2 與 RTL 的共同基礎。它**只**定義 trellis 的結構（狀態標號、次態、輸出碼字、
butterfly 配對），不含任何解碼邏輯。

## 為什麼要寫成泛用的（K 與多項式都是參數）

不是為了通用性本身，而是為了一個**免費而且很強的 oracle**：既有的通訊模擬器裡有一份
K=3 (7,5) 的 Viterbi，經過 mutation testing（分數 90.4%）而且有「與暴力 ML 枚舉相等」
的測試。把 K=3 灌進這個泛用 trellis，就能拿它當參考來驗證引擎本身；
確定引擎對了，才把 K=7 (133,171) 灌進去。

## 狀態慣例（凍結，見 docs/trellis_convention.md）

    s' = ((s << 1) | u) & (2^m - 1)          m = K - 1

也就是**新輸入從最低位進入**。於是：

    s 的 bit k = u_{t-1-k}      （bit 0 = 最近一次輸入，bit m-1 = 最舊的一次）
    進入狀態 s 的輸入位元 = s & 1
    s 的兩個前驅 = (s >> 1) 與 (s >> 1) + 2^(m-1)

這個慣例的好處是 butterfly 結構乾淨：butterfly j 吃 PM[j] 與 PM[j + 2^(m-1)]，
吐 PM[2j] 與 PM[2j+1]。

注意：既有通訊模擬器用的是**相反**的慣例（新輸入從最高位進入，`ns = (u<<1)|d1`），
所以兩邊的狀態編號對不起來。這不影響用它當 oracle——**碼字序列是一樣的**，
我們比對的是編碼器輸出與解碼後的資訊位元，不是狀態編號。

## 生成多項式的位元順序

多項式以八進位給定，最高位對應**當前輸入** u_t，最低位對應最舊的 u_{t-m}：

    g = 133₈ = 0b1011011,  m = 6
        bit 6 -> u_t      (1)
        bit 5 -> u_{t-1}  (0)
        bit 4 -> u_{t-2}  (1)
        bit 3 -> u_{t-3}  (1)
        bit 2 -> u_{t-4}  (0)
        bit 1 -> u_{t-5}  (1)
        bit 0 -> u_{t-6}  (1)
    => c0 = u_t ^ u_{t-2} ^ u_{t-3} ^ u_{t-5} ^ u_{t-6}
"""

import numpy as np

# 定案的設計參數（規格書 §3）
K_VITERBI = 7
POLYS_VITERBI = (0o133, 0o171)

# 既有通訊模擬器裡那份 K=3 (7,5) 的碼——拿來當引擎的 oracle
K_ORACLE = 3
POLYS_ORACLE = (0o7, 0o5)


class Trellis:
    """一個 rate-1/n 卷積碼的 trellis 結構。"""

    def __init__(self, K, polys):
        self.K = K
        self.polys = tuple(polys)
        self.m = K - 1                      # 記憶元個數
        self.n_states = 1 << self.m
        self.n_out = len(polys)             # 每個輸入位元產生幾個碼位元
        self.mask = self.n_states - 1
        self.half = self.n_states >> 1      # = 2^(m-1)

        # next_state[s, u]、out[s, u]（out 是 n_out 個碼位元組成的整數，polys[0] 在最高位）
        self.next_state = np.zeros((self.n_states, 2), dtype=np.int64)
        self.out = np.zeros((self.n_states, 2), dtype=np.int64)
        for s in range(self.n_states):
            for u in (0, 1):
                self.next_state[s, u] = ((s << 1) | u) & self.mask
                self.out[s, u] = self._encode_one(u, s)

        # 進入狀態 s' 的兩個前驅：survivor bit 0 -> pred0，bit 1 -> pred1
        self.pred0 = np.arange(self.n_states, dtype=np.int64) >> 1
        self.pred1 = self.pred0 + self.half

        # butterfly j：吃 PM[j] 與 PM[j+half]，吐 PM[2j] 與 PM[2j+1]
        self.n_bfly = self.half
        # bfly_out[j] = 由前驅 j、輸入 u=0 產生的碼字（見下方 §互補性）
        self.bfly_out = np.array(
            [self.out[j, 0] for j in range(self.n_bfly)], dtype=np.int64
        )

        self._check_complementarity()

    def _encode_one(self, u, s):
        """給定輸入 u 與狀態 s，回傳 n_out 個碼位元組成的整數（polys[0] 在最高位）。"""
        # 移位暫存器的內容 bits[i] = u_{t-i}，i = 0..m
        # s 的 bit k = u_{t-1-k}，所以 u_{t-i} = (s >> (i-1)) & 1（i >= 1）
        bits = [u] + [(s >> k) & 1 for k in range(self.m)]
        val = 0
        for g in self.polys:
            acc = 0
            for i in range(self.m + 1):
                if (g >> (self.m - i)) & 1:     # g 的 bit (m-i) 對應 u_{t-i}
                    acc ^= bits[i]
            val = (val << 1) | acc
        return val

    def _check_complementarity(self):
        """驗證兩個讓 ACS 只需一個 branch metric 輸入的代數性質。

        這兩條性質是 butterfly 架構的立足點。它們**不是對所有卷積碼都成立**，
        所以必須在建構 trellis 時當場驗證，而不是假設。
        """
        full = (1 << self.n_out) - 1

        # 性質 1：c(s, u=1) = ~c(s, u=0)
        #   成立條件：每個生成多項式都有「當前輸入」的抽頭，即 bit m 為 1。
        #   133₈ = 0b1011011 -> bit 6 = 1；171₈ = 0b1111001 -> bit 6 = 1。
        self.prop_u_complement = all((g >> self.m) & 1 for g in self.polys)

        # 性質 2：c(p + half, u) = ~c(p, u)
        #   成立條件：每個生成多項式都有「最舊的那個位元 u_{t-m}」的抽頭，即 bit 0 為 1
        #   ——也就是**每個八進位多項式都是奇數**。
        #   133₈ 與 171₈ 都是奇數。（注意：這裡的關鍵是 LSB，不是 MSB。）
        self.prop_p_complement = all(g & 1 for g in self.polys)

        if self.prop_u_complement:
            for s in range(self.n_states):
                assert self.out[s, 1] == (self.out[s, 0] ^ full), \
                    f"性質 1 破裂 @ s={s}"
        if self.prop_p_complement:
            for p in range(self.half):
                for u in (0, 1):
                    assert self.out[p + self.half, u] == (self.out[p, u] ^ full), \
                        f"性質 2 破裂 @ p={p}, u={u}"

    def encode(self, info_bits):
        """終止式編碼：資訊位元 + m 個歸零 tail bits。

        info_bits: (B, L) 的 uint8
        回傳:      (B, L+m, n_out) 的 uint8
        """
        info_bits = np.asarray(info_bits, dtype=np.uint8)
        B, L = info_bits.shape
        T = L + self.m
        padded = np.concatenate([info_bits, np.zeros((B, self.m), np.uint8)], axis=1)

        out = np.zeros((B, T, self.n_out), dtype=np.uint8)
        s = np.zeros(B, dtype=np.int64)
        for t in range(T):
            u = padded[:, t].astype(np.int64)
            val = self.out[s, u]
            for j in range(self.n_out):
                out[:, t, j] = (val >> (self.n_out - 1 - j)) & 1
            s = self.next_state[s, u]
        assert np.all(s == 0), "終止後編碼器必須回到狀態 0"
        return out

    def free_distance(self, max_depth=16):
        """以廣度優先搜尋算 d_free：從狀態 0 出發、非零輸入、回到狀態 0 的最小碼字重量。

        用來驗證多項式沒有打錯字。(133,171) 的 d_free = 10；(7,5) 的 d_free = 5。
        """
        best = np.inf
        # (state, weight)；只走「已經離開狀態 0」的路徑
        frontier = {}
        for u in (1,):        # 第一步必須是 1，否則沒離開全零路徑
            ns = int(self.next_state[0, u])
            w = bin(int(self.out[0, u])).count("1")
            frontier[ns] = min(frontier.get(ns, np.inf), w)

        for _ in range(max_depth):
            nxt = {}
            for s, w in frontier.items():
                if w >= best:
                    continue
                for u in (0, 1):
                    ns = int(self.next_state[s, u])
                    nw = w + bin(int(self.out[s, u])).count("1")
                    if ns == 0:
                        best = min(best, nw)
                    else:
                        if nw < nxt.get(ns, np.inf):
                            nxt[ns] = nw
            frontier = nxt
            if not frontier:
                break
        return int(best)


def viterbi_trellis():
    """本專案的 trellis：K=7, R=1/2, (133,171)。"""
    return Trellis(K_VITERBI, POLYS_VITERBI)


def oracle_trellis():
    """K=3 (7,5) —— 既有通訊模擬器裡那份碼，用來驗證引擎本身。"""
    return Trellis(K_ORACLE, POLYS_ORACLE)
