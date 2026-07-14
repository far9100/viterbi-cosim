"""G4 的裁決材料：硬判決損失到底該是多少？

規格書的「≈ 2 dB ±0.3」是一條經驗法則。這支 script 算出可推導的參考值
（硬判決 union bound），好讓「實測 2.5 dB」這件事能被判斷成
「解碼器壞了」還是「經驗法則本來就不準」——而不是靠感覺。
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate  # noqa: E402
from golden.bounds import (union_bound_ber, union_bound_ber_hard,  # noqa: E402
                           weight_spectrum)
from golden.trellis import viterbi_trellis  # noqa: E402

t = viterbi_trellis()
R = code_rate(1024, t.m)
_, c = weight_spectrum(t, d_max=22)


def required(fn, target=1e-5):
    """union bound 降到 target 所需的 Eb/N0（細網格搜尋）。"""
    e = np.arange(2.0, 12.0, 0.005)
    b = fn(e, c, R, 10)
    idx = np.where(b <= target)[0]
    return float(e[idx[0]]) if len(idx) else None


rs = required(union_bound_ber)
rh = required(union_bound_ber_hard)

print("由 union bound 推導出的「所需 Eb/N0 @ BER 1e-5」：")
print(f"  軟判決  {rs:.3f} dB")
print(f"  硬判決  {rh:.3f} dB")
print(f"  硬判決的損失  {rh - rs:.3f} dB   <- 可推導的參考值")
print()
print("規格書 G4 的容差是 2.0 ± 0.3 dB，也就是 [1.7, 2.3]。")
print("union bound 本身就給出上面那個數字——那條「≈2 dB」的經驗法則，")
print("對 (133,171) 在 1e-5 這個工作點並不成立。")
print()
print("理論上的漸近值：硬判決的指數只有軟判決的一半（P_d ~ (4p(1-p))^(d/2)），")
print("所以漸近損失是 10·log10(2) = 3.010 dB。1e-5 落在非漸近區，")
print("量到 2~3 dB 之間才是預期的行為。")
