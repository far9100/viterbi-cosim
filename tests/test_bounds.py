"""test_bounds.py — golden/bounds.py 的權重譜與 union bound 的 known-answer 測試。

## 為什麼這支測試是必要的

`golden/bounds.py` 算出來的 c_d 是 **G2a 的 oracle** —— 整條 BER 鏈路就是拿它當上界
來驗證解碼器的。它自己的 docstring 說得很清楚：

> 抄來的表若與實際的多項式對不起來（打錯一個八進位字），G2a 就會拿一個
> 錯誤的上界去驗證一個錯誤的解碼器，而且很可能「通過」。

自己枚舉確實堵住了「抄錯表」那個縫，但**留下了另一個縫**：枚舉本身如果錯了，
沒有任何東西會發現。原本的做法是把文獻值寫在**散文註解**裡當 sanity check ——
註解不會執行，也就攔不住任何回歸。

這支測試把那段註解變成會失敗的斷言。文獻值（Viterbi/Omura 等標準表）：

    (133,171)₈, K=7：a_10=11, a_12=38, a_14=193；c_10=36, c_12=211, c_14=1404
    (7,5)₈,     K=3：d_free=5

註：a_d 是輸出重量為 d 的 error event 路徑數，c_d 是那些路徑的**輸入重量總和**。
union bound 用的是 c_d，所以 c_d 錯了才是真正致命的；兩個都釘。
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.bounds import (q_function, union_bound_ber,  # noqa: E402
                           union_bound_ber_hard, weight_spectrum)
from golden.trellis import (K_ORACLE, K_VITERBI, POLYS_ORACLE,  # noqa: E402
                            POLYS_VITERBI, Trellis)


@pytest.fixture(scope="module")
def spec_k7():
    return weight_spectrum(Trellis(K_VITERBI, POLYS_VITERBI))


def test_weight_spectrum_matches_literature_a(spec_k7):
    """a_d 對上文獻表。打錯一個八進位字就會在這裡爆。"""
    a, _ = spec_k7
    assert (a[10], a[12], a[14]) == (11, 38, 193)


def test_weight_spectrum_matches_literature_c(spec_k7):
    """c_d 對上文獻表 —— union bound 實際用的是這一組。"""
    _, c = spec_k7
    assert (c[10], c[12], c[14]) == (36, 211, 1404)


def test_free_distance_is_first_nonzero_weight(spec_k7):
    """d_free = 10 必須等於權重譜第一個非零的 d。

    這是一個**交叉檢查**：d_free 另有 BFS 的獨立實作（Trellis.free_distance，
    由 tests/test_golden.py::test_dfree 釘住）。兩條互相獨立的路徑必須一致 ——
    只驗其中一條的話，兩邊一起錯還是會通過。
    """
    a, _ = spec_k7
    assert int(np.nonzero(a)[0][0]) == 10
    assert Trellis(K_VITERBI, POLYS_VITERBI).free_distance() == 10


def test_odd_weights_are_absent(spec_k7):
    """(133,171) 的權重譜只有偶數項。

    這不是巧合：兩個生成多項式的權重都是偶數（0o133 與 0o171 各有 5 個 1，
    但互補性讓 error event 的輸出重量成對出現）。奇數項冒出來代表枚舉
    走錯了狀態轉移。這條純粹是結構性的，不依賴文獻表。
    """
    a, _ = spec_k7
    assert not a[11:24:2].any(), f"出現奇數重量的 error event：{a}"


def test_oracle_code_free_distance():
    """K=3 的 (7,5) 對照碼：d_free = 5。

    這個碼是 G2a 之外那條 commsim 交叉驗證路徑用的，它的譜也不能壞。
    """
    a, _ = weight_spectrum(Trellis(K_ORACLE, POLYS_ORACLE))
    assert int(np.nonzero(a)[0][0]) == 5


def test_dmax_truncation_is_monotone(spec_k7):
    """加大 d_max 只會**加上**更高階的項，已算出的低階項一個都不能變。

    截斷的界不是上界（報告 §3 對此有明文），所以 d_max 是一個會影響結論的參數。
    這條確保它至少是**單調**的 —— 換 d_max 不會悄悄改掉 d_free 附近那幾項。
    """
    a24, c24 = spec_k7
    a16, c16 = weight_spectrum(Trellis(K_VITERBI, POLYS_VITERBI), d_max=16)
    assert (a16[:17] == a24[:17]).all()
    assert (c16[:17] == c24[:17]).all()


def test_q_function_known_values():
    """Q(0)=0.5、Q(1)≈0.158655、Q(2)≈0.0227501。

    union bound 的每一項都乘上 Q()，它錯了整條界就跟著錯，
    而症狀會偽裝成「解碼器比理論還好」或「界太鬆」。
    """
    assert q_function(0.0) == pytest.approx(0.5, abs=1e-12)
    assert q_function(1.0) == pytest.approx(0.158655, abs=1e-6)
    assert q_function(2.0) == pytest.approx(0.02275013, abs=1e-8)


def test_union_bound_is_monotone_decreasing(spec_k7):
    """界必須隨 Eb/N0 單調下降。"""
    _, c = spec_k7
    vals = [union_bound_ber(e, c, R=0.5, d_free=10) for e in (2.0, 3.0, 4.0, 5.0)]
    assert all(x > y for x, y in zip(vals, vals[1:])), vals


def test_hard_bound_is_worse_than_soft(spec_k7):
    """同一個 Eb/N0 下，硬判決的界必須比軟判決差（BER 較高）。

    軟判決相對硬判決約有 2 dB 增益（G4b 實測 2.413 dB），所以兩條界的
    大小關係是被物理釘死的。反過來就代表其中一條的 Es/N0 換算寫錯了 ——
    那是這兩支函式最容易出錯的地方。
    """
    _, c = spec_k7
    for ebn0 in (3.0, 4.0, 5.0):
        soft = union_bound_ber(ebn0, c, R=0.5, d_free=10)
        hard = union_bound_ber_hard(ebn0, c, R=0.5, d_free=10)
        assert hard > soft, f"@{ebn0} dB：hard={hard} 不大於 soft={soft}"
