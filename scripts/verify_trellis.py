"""驗證 trellis 的代數性質——在把它們寫進凍結文件之前。

順序很重要：先驗證，再記錄。反過來（先寫文件再實作）就是把猜測固化成規格。
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.trellis import Trellis, oracle_trellis, viterbi_trellis  # noqa: E402

# 既有通訊模擬器（不可 pip install，路徑含空白字元，只能用 sys.path 注入）
COMMSIM = "/mnt/c/Users/fartw/OneDrive/Desktop/github/communications relay simulator"
sys.path.insert(0, COMMSIM)


def main():
    t = viterbi_trellis()
    o = oracle_trellis()

    print("=== K=7, (133,171)")
    print(f"  m (記憶元)          {t.m}")
    print(f"  狀態數              {t.n_states}")
    print(f"  butterfly 數        {t.n_bfly}")
    print(f"  d_free              {t.free_distance()}   (預期 10)")
    print(f"  性質1 c(s,1)=~c(s,0)          {t.prop_u_complement}"
          f"   （條件：每個多項式 bit m = 1）")
    print(f"  性質2 c(p+32,u)=~c(p,u)       {t.prop_p_complement}"
          f"   （條件：每個多項式為奇數，即 bit 0 = 1）")
    print(f"  133八進位 = {0o133:#09b}  奇數? {0o133 % 2 == 1}")
    print(f"  171八進位 = {0o171:#09b}  奇數? {0o171 % 2 == 1}")

    print("\n=== K=3, (7,5) —— oracle")
    print(f"  d_free              {o.free_distance()}   (預期 5)")
    print(f"  性質1 / 性質2       {o.prop_u_complement} / {o.prop_p_complement}")

    # --- butterfly 結構 ---
    print("\n=== butterfly 結構（前 4 個）")
    for j in range(4):
        s0, s1 = 2 * j, 2 * j + 1
        print(f"  bfly {j:2d}: PM[{j}], PM[{j + t.half}] -> PM[{s0}], PM[{s1}]"
              f"   | c({j},0)={t.out[j,0]:02b}  c({j+t.half},0)={t.out[j+t.half,0]:02b}")
        assert t.pred0[s0] == j and t.pred1[s0] == j + t.half
        assert t.pred0[s1] == j and t.pred1[s1] == j + t.half
        assert (s0 & 1) == 0 and (s1 & 1) == 1     # 進入狀態的輸入位元 = s & 1
    print("  前驅關係與「輸入位元 = s & 1」皆驗證通過")

    # --- 手算表（要放進凍結文件的那張）---
    print("\n=== 手算表：s=0..3, u=0/1")
    print("  s   u   s'=(s<<1|u)&63   c0 c1")
    for s in range(4):
        for u in (0, 1):
            ns = int(t.next_state[s, u])
            c = int(t.out[s, u])
            print(f"  {s:2d}  {u}   {ns:2d}              {(c >> 1) & 1}  {c & 1}")

    # --- 與既有模擬器的編碼器逐位元組比對（K=3）---
    print("\n=== oracle：K=3 編碼器 vs commsim.coding.conv_encode")
    from commsim.coding import conv_encode  # noqa: E402

    rng = np.random.default_rng(20260714)
    L = 200
    B = 50
    info = rng.integers(0, 2, size=(B, L), dtype=np.uint8)

    mine = o.encode(info)                       # (B, L+2, 2)
    theirs = conv_encode(info.reshape(-1), L).reshape(B, L + 2, 2)

    same = np.array_equal(mine, theirs)
    print(f"  {B} frames x {L} info bits，碼字逐位元組相等： {same}")
    if not same:
        d = np.argwhere(mine != theirs)
        print(f"  首個不同處: {d[0] if len(d) else '?'}")
        return 1

    print("\n全部通過。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
