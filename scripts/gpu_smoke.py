"""gpu_smoke.py — 驗證 RTX 5070（Blackwell, sm_120）能執行本專案實際會用到的整數運算。

規格書 §5 要求「環境設置的第一步是跑一個最小整數 kernel 驗證 GPU 可用」。這裡刻意不只做
torch.cuda.is_available()——那個在 CPU-only wheel 上也可能為 True 卻在第一次 kernel launch
時才炸 "no kernel image available"。本檔實際跑一次 ACS（add-compare-select）的整數運算，
也就是 GPU 掃描的內迴圈，並與 numpy 逐位元組比對。

為什麼比對必須是「逐位元組相等」而不是「近似相等」：整條驗證鏈路的立足點是 bit-accurate。
GPU 版 golden model（L2-GPU）之後要負責產生 Tier B 的期望輸出，若它與 CPU 版 golden 有任何
一個 bit 不同，C2 就失去意義。這正是計畫中新增的 C2' 比對點；本檔是它的最小前哨。

特別注意 tie-break：torch.minimum 是逐元素運算、不回傳索引，所以 survivor bit 必須自己算。
`a <= b` 與 `a < b` 的選擇會「默默」決定平手時選哪個前驅——在 Q=3 時整數平手很常見，
選錯方向不會報錯，只會讓 C2 在 RTL 上線後噴出大量 mismatch。全專案統一採「平手選 survivor bit 0」，
對應 np.argmin 的語意（回傳第一個最小值），因此這裡用 `a <= b`。
"""

import sys

import numpy as np


def acs_numpy(pm_a, pm_b, bm_a, lambda_max, w_bits):
    """CPU 參考版的 ACS：與 golden/viterbi_fx.py 未來的實作採同一組定義。

    pm_a / pm_b 是兩個前驅狀態的 path metric（已 mod 2^W 化簡）。
    bm_a 是前驅 a 的 branch metric；前驅 b 的碼字與 a 互補，故 bm_b = lambda_max - bm_a
    （g0=133, g1=171 的 MSB tap 都是 1，這個互補性對 K=7 恆成立）。
    """
    mask = (1 << w_bits) - 1
    sum_a = (pm_a + bm_a) & mask
    sum_b = (pm_b + (lambda_max - bm_a)) & mask

    # 關鍵：比較必須在 modulo 算術下進行。把 (sum_b - sum_a) 解讀為 W-bit 有號數再取符號，
    # 才能在 wraparound 下得到正確的比較結果。直接比 sum_a < sum_b 在跨越 2^W 邊界時會反轉。
    diff = (sum_b - sum_a) & mask
    sign = (diff >> (w_bits - 1)) & 1          # 1 表示 signed(diff) < 0，即 sum_b < sum_a
    sel_a = sign == 0                          # signed(diff) >= 0 ⇒ 選 A（含 diff==0 的平手）

    pm_out = np.where(sel_a, sum_a, sum_b)
    surv = np.where(sel_a, 0, 1).astype(np.uint8)
    return pm_out, surv


def acs_torch(torch, pm_a, pm_b, bm_a, lambda_max, w_bits):
    """GPU 版的 ACS——與 acs_numpy 是同一組公式，逐行對應。"""
    mask = (1 << w_bits) - 1
    sum_a = (pm_a + bm_a) & mask
    sum_b = (pm_b + (lambda_max - bm_a)) & mask

    diff = (sum_b - sum_a) & mask
    sign = (diff >> (w_bits - 1)) & 1
    sel_a = sign == 0

    pm_out = torch.where(sel_a, sum_a, sum_b)
    surv = torch.where(sel_a,
                       torch.zeros_like(sum_a),
                       torch.ones_like(sum_a)).to(torch.uint8)
    return pm_out, surv


def main():
    try:
        import torch
    except ImportError:
        print("FAIL: torch 未安裝")
        return 1

    print(f"torch                {torch.__version__}")
    print(f"torch.version.cuda   {torch.version.cuda}")
    print(f"cuda.is_available    {torch.cuda.is_available()}")

    if not torch.cuda.is_available():
        print("FAIL: CUDA 不可用")
        return 1

    name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    print(f"device               {name}")
    print(f"compute capability   sm_{cap[0]}{cap[1]}")

    if cap[0] < 12:
        print(f"WARN: 預期 sm_120（Blackwell），實得 sm_{cap[0]}{cap[1]}")

    # --- 實際的整數 kernel：一整層 trellis 的 ACS，跨 frame 批次化 ---
    # 形狀刻意取成掃描時的真實形狀：B 個 frame × 32 個 butterfly。
    W_BITS = 10
    Q = 4
    LAMBDA_MAX = 2 * ((1 << Q) - 1)   # 30
    B, NBFLY = 4096, 32

    rng = np.random.default_rng(20260714)
    mask = (1 << W_BITS) - 1
    pm_a_np = rng.integers(0, mask + 1, size=(B, NBFLY), dtype=np.int64)
    pm_b_np = rng.integers(0, mask + 1, size=(B, NBFLY), dtype=np.int64)
    bm_a_np = rng.integers(0, LAMBDA_MAX + 1, size=(B, NBFLY), dtype=np.int64)

    pm_ref, surv_ref = acs_numpy(pm_a_np, pm_b_np, bm_a_np, LAMBDA_MAX, W_BITS)

    dev = torch.device("cuda")
    pm_gpu, surv_gpu = acs_torch(
        torch,
        torch.from_numpy(pm_a_np).to(dev),
        torch.from_numpy(pm_b_np).to(dev),
        torch.from_numpy(bm_a_np).to(dev),
        LAMBDA_MAX, W_BITS,
    )
    torch.cuda.synchronize()

    pm_ok = np.array_equal(pm_gpu.cpu().numpy(), pm_ref)
    surv_ok = np.array_equal(surv_gpu.cpu().numpy(), surv_ref)

    # 平手的樣本數：這是 tie-break 語意有沒有被真的測到的證據。
    # 若為 0，代表這個測試根本沒碰到平手路徑，通過了也不能算數。
    sum_a = (pm_a_np + bm_a_np) & mask
    sum_b = (pm_b_np + (LAMBDA_MAX - bm_a_np)) & mask
    n_tie = int(np.sum(sum_a == sum_b))

    print(f"ACS 整數 kernel      B={B} × {NBFLY} butterflies, Q={Q}, W={W_BITS}")
    print(f"  pm       逐位元組相等  {pm_ok}")
    print(f"  survivor 逐位元組相等  {surv_ok}")
    print(f"  平手樣本數             {n_tie}（>0 才代表 tie-break 語意有被測到）")

    if pm_ok and surv_ok and n_tie > 0:
        print("PASS: sm_120 整數路徑可用，且與 numpy 逐位元組相等（含平手情形）")
        return 0
    print("FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
