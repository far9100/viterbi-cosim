"""跑 M1 的量測之前，先確認兩件事：
   (1) 重量分布算對了（與文獻值對照）
   (2) 解碼器夠快，BER 到 1e-5 是負擔得起的
"""

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate, measure_ber  # noqa: E402
from golden.bounds import union_bound_ber, weight_spectrum  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402

t = viterbi_trellis()

print("=== (133,171) 的重量分布（枚舉算出，非抄自文獻）")
a, c = weight_spectrum(t, d_max=22)
print("   d :  a_d      c_d      文獻 a_d / c_d")
lit = {10: (11, 36), 12: (38, 211), 14: (193, 1404), 16: (1331, 11633)}
ok = True
for d in range(10, 23, 2):
    ref = lit.get(d)
    ref_s = f"{ref[0]} / {ref[1]}" if ref else "-"
    mark = ""
    if ref:
        good = (a[d] == ref[0] and c[d] == ref[1])
        ok &= good
        mark = "  OK" if good else "  <<< 不符"
    print(f"  {d:3d} : {a[d]:6d}  {c[d]:8d}      {ref_s}{mark}")
print(f"  與文獻一致: {ok}")

n_info = 1024
R = code_rate(n_info, t.m)
print(f"\n  終止碼率 R = {R:.6f}  (名目 0.5)")
for e in (3.0, 4.0, 4.5, 5.0):
    ub = float(union_bound_ber(e, c, R, 10))
    print(f"  union bound @ {e:.1f} dB = {ub:.3e}")

print("\n=== 解碼器速度（決定 BER 能跑多深）")
for kind, cfg in [
    ("float soft D=64", {"kind": "float", "D": 64, "metric": "soft"}),
    ("fx Q=4 W=10 D=32", {"kind": "fx", "Q": 4, "W": 10, "D": 32, "clip": 2.0}),
]:
    t0 = time.time()
    r = measure_ber(t, n_info, 3.0, cfg, seed=1,
                    min_errors=60, max_bits=int(2e6), batch_frames=200)
    dt = time.time() - t0
    rate = r["n_bits"] / dt
    print(f"  {kind:18s}  BER={r['ber']:.3e}  {r['n_bits']:>9,} bits / {dt:5.1f}s"
          f"  = {rate/1e3:6.0f} k info-bit/s")
    print(f"                      -> 跑到 1e-5（需 ~2e7 bits）約需 "
          f"{2e7/rate/60:.1f} 分鐘/點")
