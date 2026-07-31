"""gate-level 功耗的煙霧測試：掃 dump 深度，找「最淺但覆蓋率仍 >= 99%」的那一個。

$dumpvars 的深度是速度與覆蓋率的取捨，而**它必須被量出來，不能用猜的**：
太深 -> dump 到 cell 內部（34k 個 cell × 十來條內部 net = 46 萬條），模擬慢到不能用，
        而且 OpenSTA 根本不需要它們（cell 的內部功耗來自 Liberty 表）。
太淺 -> 漏掉 netlist 的 net -> annotation 覆蓋率掉 -> OpenSTA 靜靜地套用預設猜測。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ppa.power as P  # noqa: E402
from scripts.gates import REPO  # noqa: E402

tag = "Q4_W10_D64"
netlist = os.path.join(REPO, "ppa", "out", "synth", f"net_{tag}.v")
os.makedirs(P.OUT, exist_ok=True)

print("=== gate-level 編譯（TB 的參數用 -P 覆寫成 netlist 的 Q=4 W=10 D=64 NINFO=1024）")
vvp, n_cells = P.build_gl(tag, netlist, 4, 10, 64, 1024)
print(f"    {n_cells} 種 cell")

print("=== 激勵（真實 AWGN, 3 dB）")
sd = os.path.join(P.OUT, "smoke_stim")
sp, dp, T = P.make_stimulus(4, 10, 64, 2.5, 3.0, sd)

print()
print(f"{'depth':>6} {'nets':>9} {'SAIF':>9} {'sim':>8} {'annot':>8}  C2")
for depth in (2, 3, 4):
    t0 = time.time()
    saif, ok, n_nets, dt, out = P.run_saif(tag, vvp, sp, dp, T, 3.0,
                                           frames=2, depth=depth)
    if not ok:
        print(f"{depth:>6}  gate-level C2 FAIL")
        print(out[-1200:])
        sys.exit(1)
    sta = P.run_sta(tag, netlist, saif, 3.0)
    pr = P.parse_power(sta)
    ann = pr.get("annot_pct", 0.0)
    print(f"{depth:>6} {n_nets:>9,} {os.path.getsize(saif)/1e6:>7.1f}MB "
          f"{dt:>6.0f}s {ann:>7.2f}%  PASS")
    if ann >= 99.0:
        print(f"\n  -> depth={depth} 已達 >= 99% 覆蓋率。")
        print("     功耗（2 frames，只是煙霧測試，數字之後會重跑）：")
        for k in ["total"] + P.BLOCKS:
            v = pr.get(k)
            if v:
                print(f"       {k:8s} {v['total']*1e3:9.4f} mW")
        sys.exit(0)

print("\n  沒有任何深度達到 99% —— 需要追查命名對不上的問題。")
sys.exit(1)
