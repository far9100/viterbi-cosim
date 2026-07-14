"""union bound 對 d_max 的收斂性。

G4a 在 6.5 dB 「違反」了上界（實測 1.2329e-5 vs 界 1.1891e-5，高出 4%）。
違反一條定理只有三種可能：解碼器錯了、量測錯了、或**界算錯了**。

嫌疑最大的是界：`weight_spectrum(d_max=22)` 把 d>22 的項全部丟掉，
而**截斷過的 union bound 不是上界**——它比真正的界小。
軟判決的尾巴被 Q 函數壓死（可忽略），但硬判決的每項只以 (4p(1-p))^(d/2) 衰減，
而 c_d 每兩步成長約 6.6 倍。兩者相乘，尾巴未必可忽略。

這支 script 把 d_max 逐步加大，看界收斂到哪裡。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate  # noqa: E402
from golden.bounds import (union_bound_ber, union_bound_ber_hard,  # noqa: E402
                           weight_spectrum)
from golden.trellis import viterbi_trellis  # noqa: E402

t = viterbi_trellis()
R = code_rate(1024, t.m)

MEASURED_HARD_65 = 1.23291015625e-05    # 實測值（data/cache 裡的那個點）

print("硬判決 union bound @ 6.5 dB，隨 d_max 的收斂：")
print(f"{'d_max':>6} {'bound':>12} {'相對前一個':>10}  {'實測/界':>8}")
prev = None
for dmax in (18, 22, 26, 30, 34, 38, 42):
    _, c = weight_spectrum(t, d_max=dmax)
    b = float(union_bound_ber_hard(6.5, c, R, 10))
    rel = f"{(b - prev)/prev*100:+.1f}%" if prev else "   -"
    print(f"{dmax:>6} {b:>12.4e} {rel:>10}  {MEASURED_HARD_65/b:>8.3f}")
    prev = b

print()
print("軟判決 union bound @ 4.5 dB（對照：尾巴應該可忽略）：")
prev = None
for dmax in (18, 22, 26, 30):
    _, c = weight_spectrum(t, d_max=dmax)
    b = float(union_bound_ber(4.5, c, R, 10))
    rel = f"{(b - prev)/prev*100:+.2f}%" if prev else "   -"
    print(f"{dmax:>6} {b:>12.4e} {rel:>10}")
    prev = b
