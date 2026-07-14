"""traceback.py — survivor 回溯。L1（浮點）與 L2（定點）共用。

語意由 docs/traceback_convention.md 凍結。**RTL 必須產生逐位元相同的解碼位元。**

共用是對的：traceback 是**演算法**，不是 RTL 的實作細節。規格書 §2.1 禁止的是
golden model 模仿 RTL 的 pipeline / handshaking / 延遲，不是禁止兩邊共用演算法定義。
L1 與 L2 的差別只在前向的算術（浮點歐氏距離 vs 整數距離 + modulo PM），
回溯邏輯完全相同——這樣 C1 量到的才純粹是「量化」的代價。
"""

import numpy as np


def _pred(surv_t, s, m_bit):
    """一步回溯：把 s_{t+1} 映回 s_t。

    surv_t : (B, n_states) 該 stage 的 survivor bits
    s      : (B,) 目前狀態
    m_bit  : 回填的位元位置 = m - 1（K=7 時為 5）
    """
    B = s.shape[0]
    sv = surv_t[np.arange(B), s].astype(np.int64)
    return (s >> 1) | (sv << m_bit)


def traceback(surv, best, D, n_info, m, mode="window"):
    """由 survivor 陣列還原資訊位元。

    surv   : (B, T, n_states) uint8，surv[t][s] = 進入狀態 s 的 survivor bit
    best   : (B, T) 每個 stage 結束後 PM 最小的狀態（mode='ml' 時不使用）
    D      : 回溯深度
    n_info : 資訊位元數（T = n_info + m）
    m      : 記憶元數（K−1）
    mode   : 'window' = uniform depth D 的 sliding window（C2 的比對標的）
             'ml'     = 由終止狀態 0 全幀回溯（對照組）

    回傳 (B, n_info) 的 uint8。
    """
    B, T, _ = surv.shape
    assert T == n_info + m
    m_bit = m - 1
    dec = np.zeros((B, T), dtype=np.uint8)

    if mode == "ml":
        # 全幀回溯：從已知的終止狀態 s_T = 0 出發
        s = np.zeros(B, dtype=np.int64)
        for t in range(T - 1, -1, -1):
            dec[:, t] = (s & 1).astype(np.uint8)
            s = _pred(surv[:, t, :], s, m_bit)
        return dec[:, :n_info]

    if mode != "window":
        raise ValueError(f"未知的 mode: {mode}")

    # --- 主體：每個 stage 從 min-PM 狀態往回追固定 D 步，輸出 1 個位元 ---
    #
    # 這裡把「對每個 t 各追 D-1 步」改寫成「所有 t 一起追，一次一步」。
    # 語意完全相同（見 traceback_slow，測試會逐位元比對兩者），但 numpy 的呼叫次數
    # 從 (T-D+1)x(D-1) ≈ 61,000 降到 D-1 ≈ 63 —— BER 要跑到 1e-5 需要 ~10^7 個位元，
    # 逐 t 的寫法光是 Python/numpy 的呼叫開銷就會吃掉大部分時間。
    starts = np.arange(D - 1, T)                     # 每個要輸出位元的 stage t
    s = best[:, starts].astype(np.int64)             # (B, Nt) = s_{t+1}
    bidx = np.arange(B)[:, None]
    for k in range(D - 1):
        sv = surv[bidx, (starts - k)[None, :], s]    # (B, Nt)
        s = (s >> 1) | (sv.astype(np.int64) << m_bit)
    dec[:, starts - D + 1] = (s & 1).astype(np.uint8)   # = u_{t-D+1}

    # --- 尾端：利用 termination 沖出剩下的 D−1 個位元 ---
    # 這 D−1 個位元用「從已知終止狀態出發的精確回溯」解，比 sliding window 更好。
    # 真實硬體也是這樣：frame 結束時 survivor 記憶體裡還留著最後幾個 stage。
    s = np.zeros(B, dtype=np.int64)              # s_T = 0
    for t in range(T - 1, T - D, -1):
        dec[:, t] = (s & 1).astype(np.uint8)
        s = _pred(surv[:, t, :], s, m_bit)

    return dec[:, :n_info]


def traceback_slow(surv, best, D, n_info, m, mode="window"):
    """逐 stage 的參考實作。慢，但一眼就能看出它就是 traceback_convention.md 的字面翻譯。

    只用在測試裡：它與上面向量化版本的輸出必須逐位元相同。
    向量化是為了速度，不該是為了聰明——所以要有一個笨版本盯著它。
    """
    B, T, _ = surv.shape
    m_bit = m - 1
    dec = np.zeros((B, T), dtype=np.uint8)

    if mode == "ml":
        s = np.zeros(B, dtype=np.int64)
        for t in range(T - 1, -1, -1):
            dec[:, t] = (s & 1).astype(np.uint8)
            s = _pred(surv[:, t, :], s, m_bit)
        return dec[:, :n_info]

    for t in range(D - 1, T):
        s = best[:, t].astype(np.int64)
        for k in range(D - 1):
            s = _pred(surv[:, t - k, :], s, m_bit)
        dec[:, t - D + 1] = (s & 1).astype(np.uint8)

    s = np.zeros(B, dtype=np.int64)
    for t in range(T - 1, T - D, -1):
        dec[:, t] = (s & 1).astype(np.uint8)
        s = _pred(surv[:, t, :], s, m_bit)

    return dec[:, :n_info]
