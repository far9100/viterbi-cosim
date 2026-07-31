"""m9_sweep.py — M9 的功耗量測：最佳化過的設計上，null 還在不在？

判準與事前預測凍結於 `docs/lowpower_baseline.md`（量測前）。本檔只負責跑與記錄，
**不負責裁決**——裁決由 `scripts/m9_gate.py` 依那份文件的判準做。

三態（全部先過 C2，見 `ppa/verify_cg.py`）：

    B0   rtl/           無 clock gating   —— M5 的現況，數字不重算
    B0'  rtl_lowpower/  無 clock gating   —— **RTL 改寫的混淆因子控制組**
    B1'  rtl_lowpower/  有 clock gating   —— 最佳化過的設計

沒有 B0' 這一欄，就無法把 B0→B1' 的差異歸給 clock gating——`rtl_lowpower/` 的
reset-in-enable 改寫本身在面積上就要付 +4.04%（見 `rtl_lowpower/README.md`）。

主掃描沿用 M5 的同一組 SNR 點與同一支 `make_stimulus`（同 seed），
所以兩條曲線逐點可比。
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ppa.power as P  # noqa: E402
from ppa.run_power import (DUMP_DEPTH, FRAMES, SNR_SWEEP,  # noqa: E402
                           evidence_only, point)
from ppa.synth import synth  # noqa: E402
import scripts.design as DESIGN  # noqa: E402
from scripts.gates import DATA, REPO  # noqa: E402

# 時間預算：harness 有 10 分鐘上限，而 32 個閘級點要跑數小時。
# 用光就乾淨結束並回傳 1，由 Makefile 的 until 迴圈續跑——比照 ppa/run_power.py。
# point() 有快取，續跑時已算過的點瞬間返回；最後一趟全命中才寫出完整的 power_m9.json。
#
# 從環境變數讀（比照 sweep/grid_runner.py），這樣續跑這條路徑可以用一個很小的預算
# 便宜地測試，而不必等完整的數小時掃描——否則它只會在真正的冷跑裡第一次被執行到。
BUDGET_S = float(os.environ.get("BUDGET", "460"))

LP_RTL = "/work/rtl_lowpower"

# 單一來源：scripts/design.py。ORDER_POWER 的第一個就是主掃描組態
# （與 M5 相同，功耗 vs SNR 的交付結果就是在它上面量的），其餘三個只量 3 dB。
_W = DESIGN.winners(DESIGN.ORDER_POWER)
MAIN = _W[0]
OTHERS = _W[1:]

VARIANTS = DESIGN.VARIANTS                             # B0' / B1'


def ensure_netlists():
    """先把兩個變體的 netlist 都合出來（B0 的不動）。"""
    todo = [MAIN] + OTHERS
    for suffix, cg in VARIANTS:
        for Q, W, D, _clip in todo:
            tag = f"Q{Q}_W{W}_D{D}{suffix}"
            net = os.path.join(REPO, "ppa", "out", "synth", f"net_{tag}.v")
            if os.path.exists(net):
                print(f"  [快取] {tag}", flush=True)
                continue
            t0 = time.time()
            r = synth(Q, W, D, clock_gating=cg, rtl_dir=LP_RTL,
                      tag_suffix="_rtlv")
            print(f"  [合成] {tag}  area {r['total_area_um2']:.1f} µm²  "
                  f"({time.time() - t0:.0f}s)", flush=True)


def main():
    t_start = time.time()

    print("=== M9：先確保兩個變體的 netlist 都在")
    ensure_netlists()

    rows = []
    print(f"\n=== 主掃描 Q{MAIN[0]}_W{MAIN[1]}_D{MAIN[2]}：SNR {SNR_SWEEP}")
    for suffix, _cg in VARIANTS:
        for snr in SNR_SWEEP:
            if time.time() - t_start > BUDGET_S:
                print("時間預算用盡，乾淨結束。再跑一次即可續做。")
                return 1
            Q, W, D, clip = MAIN
            t0 = time.time()
            r = point(Q, W, D, clip, snr, variant=suffix)
            r["variant"] = suffix
            rows.append(r)
            print(f"  {r['tag']:22s} snr={snr}  annot={r['annot_pct']:.1f}%  "
                  f"P={r.get('p_total_w', 0) * 1e3:7.3f} mW  "
                  f"[tb {r.get('p_u_tb_w', 0) * 1e3:6.3f}  "
                  f"acs {r.get('p_u_acs_w', 0) * 1e3:6.3f}  "
                  f"minpm {r.get('p_u_minpm_w', 0) * 1e3:6.3f}]  "
                  f"({time.time() - t0:.0f}s)", flush=True)

    print("\n=== 其餘三個組態（只量 3 dB）")
    for suffix, _cg in VARIANTS:
        for Q, W, D, clip in OTHERS:
            if time.time() - t_start > BUDGET_S:
                print("時間預算用盡，乾淨結束。再跑一次即可續做。")
                return 1
            r = point(Q, W, D, clip, 3.0, variant=suffix)
            r["variant"] = suffix
            rows.append(r)
            print(f"  {r['tag']:22s} P={r.get('p_total_w', 0) * 1e3:7.3f} mW",
                  flush=True)

    # 列序由上面兩段的常數迴圈（VARIANTS × SNR_SWEEP、VARIANTS × OTHERS）唯一決定，
    # 與快取命中與否無關，所以不需要再排序一次。**檔案只在完整跑完一趟時才寫**——
    # 預算用盡是 return 1，不是寫出半份 power_m9.json。
    #
    # evidence_only 剝掉 sim_s / wall_s：它們是 wall-clock 遙測，每次都會變。
    # 原本這裡是直接 json.dump(rows)，沒有沿用 run_power.py 的剝除函式，
    # 於是 git 追蹤的證據檔帶著計時欄位進庫——這與 `2026-07-16-06` 修掉的是同一個病。
    out = os.path.join(DATA, "power_m9.json")
    with open(out, "w") as f:
        json.dump({"points": [evidence_only(r) for r in rows]}, f, indent=2)
    print(f"\n-> {out}（{len(rows)} 點）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
