"""m2_gate.py — M2 的驗收：C2′、全網格、winner 選擇、BER floor 的負向展示。

## Winner 要怎麼選才誠實

本專案的重點是**能量**，所以 winner 不該只看 BER。但**真正的硬體成本要等 M5 合成**
才知道；現在硬掰一個綜合成本分數，只會把假設偽裝成結論。

所以做法是：**沿著「所需 Eb/N0」與「已知會支配面積的那個量」挑點，並把理由寫下來**，
而不是造一個加權分數。

已知（M0 的 counter 煙霧測試 + 計畫的風險 R1）：**survivor 記憶體支配面積**，
而它的大小是 64 × 3D 位元——**只跟 D 有關，與 Q、W 都無關**。
所以 D 是成本的第一軸；第二軸是 Q（它唯一決定最小安全 W，進而決定 ACS 的資料路徑寬度）。
"""

import itertools
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ref_float import commsim  # noqa: E402
from scripts.gates import REPO, Run  # noqa: E402
from sweep.grid_runner import (CACHE, CLIPS, DS, QS, UNSAFE,  # noqa: E402
                               min_safe_W)

TARGET = 1e-5
REQ_FS = 4.137          # M1 量到的「未量化 soft, D=64」所需 Eb/N0（data/results_m1.csv）

FIELDS = ["Q", "clip", "W", "D", "snr_db", "ber", "n_errors", "n_bits",
          "ci_low", "ci_high"]


def load_all():
    rows = []
    for f in os.listdir(CACHE):
        if f.endswith(".json"):
            with open(os.path.join(CACHE, f)) as fh:
                rows.append(json.load(fh))
    return rows


def required(rows, Q, clip, W, D):
    _, _, _, metrics = commsim()
    c = sorted([r for r in rows
                if r["Q"] == Q and r["clip"] == clip
                and r["W"] == W and r["D"] == D],
               key=lambda r: r["snr_db"])
    if not c:
        return None
    return metrics.ebn0_at_target_ber([r["snr_db"] for r in c],
                                      [r["ber"] for r in c], TARGET)


def main():
    rows = load_all()
    run = Run("m2_sweep", milestone="M2")

    # ---------- C2′ ----------
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "sweep/test_c2prime.py", "-q"],
        cwd=REPO, capture_output=True, text=True)
    n_pass = 0
    for line in p.stdout.splitlines():
        if "passed" in line:
            n_pass = int(line.split()[0])
    run.check("C2' L2-CPU vs L2-GPU 位元級相等", p.returncode == 0,
              measured=f"{n_pass} 個測試通過", expected="零 mismatch",
              tolerance="零容忍",
              detail="涵蓋全部 12 個 (Q,W) 格點（含 4 個會 wrap 的不安全格點）、4 個 D、"
                     "4 個 clip，外加 GPU 編碼器與量化器的逐位元組比對。"
                     "並證實測試真的碰到平手（85072 次）——torch.minimum 不回傳索引，"
                     "平手方向選錯不會報錯，只會讓整個掃描的 BER 悄悄偏掉。")

    # ---------- 全網格 ----------
    grid = []
    for Q, clip, D in itertools.product(QS, CLIPS, DS):
        W = min_safe_W(Q)
        r = required(rows, Q, clip, W, D)
        if r is None:
            continue
        grid.append({"Q": Q, "clip": clip, "W": W, "D": D,
                     "required_ebn0_db": round(r, 4),
                     "loss_vs_float_db": round(r - REQ_FS, 4)})

    n_expect = len(QS) * len(CLIPS) * len(DS)
    run.check("M2 全網格掃描", len(grid) == n_expect,
              measured=f"{len(grid)} / {n_expect} 個組態有 1e-5 交叉點",
              expected="全部", tolerance="—",
              detail="BER 的軸是 (Q, clip, D)，不是 (Q, clip, W, D)。"
                     "W 不影響 BER —— 那是 G6 的推論，且已由 C2′ 直接比對**解碼位元**驗證，"
                     "不是假設。W 只影響 PPA。")

    # ---------- 不安全格點的 BER floor（G6 的負向展示）----------
    floors = []
    for Q, W in UNSAFE:
        c = sorted([r for r in rows if r["Q"] == Q and r["W"] == W and r["D"] == 32],
                   key=lambda r: r["snr_db"])
        if not c or c[-1]["ber"] <= 0:
            continue
        floors.append({
            "Q": Q, "W": W,
            "ber_lo_snr": c[0]["ber"], "snr_lo": c[0]["snr_db"],
            "ber_hi_snr": c[-1]["ber"], "snr_hi": c[-1]["snr_db"],
            "decades_dropped": round(float(np.log10(c[0]["ber"] / c[-1]["ber"])), 2),
        })

    safe_ref = sorted([r for r in rows if r["Q"] == 4 and r["W"] == 10
                       and r["D"] == 32 and r["clip"] == 2.0],
                      key=lambda r: r["snr_db"])
    ref_dec = (float(np.log10(safe_ref[0]["ber"] / safe_ref[-1]["ber"]))
               if safe_ref and safe_ref[-1]["ber"] > 0 else 0.0)

    worst = max((f["decades_dropped"] for f in floors), default=99.0)
    run.check("G6 負向：不安全格點出現 BER floor", worst < 2.0,
              measured=f"最多只掉 {worst:.2f} 個數量級（2→7 dB）",
              expected="< 2 個數量級", tolerance="—",
              detail=f"對照：安全組態 (Q=4,W=10) 在 4.0→5.5 dB 這段就掉了 {ref_dec:.2f} 個數量級。"
                     "字寬不足時 wraparound 讓 modulo 比較反轉，症狀是"
                     "**高 SNR 出現 BER floor、低 SNR 完全正常**——靠看 BER 曲線 debug 極慢，"
                     "所以 G6 的 assertion 才要在 stage 0 就抓到它。")

    # ---------- winner ----------
    best = min(grid, key=lambda g: g["required_ebn0_db"])
    tol = 0.10
    near = [g for g in grid if g["required_ebn0_db"] <= best["required_ebn0_db"] + tol]

    min_D = min(near, key=lambda g: (g["D"], g["required_ebn0_db"]))
    min_Q = min(near, key=lambda g: (g["Q"], g["required_ebn0_db"]))
    cand = [g for g in near if g["Q"] <= 4 and g["D"] <= 32]
    mid = min(cand, key=lambda g: g["required_ebn0_db"]) if cand else min_D
    textbook = min([g for g in grid if g["Q"] == 3 and g["D"] == 32],
                   key=lambda g: g["required_ebn0_db"])

    winners, seen = [], set()
    for g, why in [
        (best, "BER 最佳（不計成本）"),
        (min_D, f"D 最小、且距最佳 ≤ {tol} dB —— survivor 記憶體 = 64×3D 位元，支配面積"),
        (min_Q, f"Q 最小、且距最佳 ≤ {tol} dB —— Q 唯一決定最小安全 W，進而決定 ACS 寬度"),
        (mid, "折衷：Q ≤ 4 且 D ≤ 32"),
        (textbook, "教科書組態 Q=3, D=32（對照）"),
    ]:
        k = (g["Q"], g["clip"], g["D"])
        if k in seen:
            continue
        seen.add(k)
        w = dict(g)
        w["rationale"] = why
        w["survivor_bits"] = 64 * 3 * g["D"]
        winners.append(w)

    run.csv("m2_grid.csv",
            ["Q", "clip", "W", "D", "required_ebn0_db", "loss_vs_float_db"], grid)
    run.csv("m2_winners.csv",
            ["Q", "clip", "W", "D", "required_ebn0_db", "loss_vs_float_db",
             "survivor_bits", "rationale"], winners)
    run.csv("m2_ber_floor.csv",
            ["Q", "W", "snr_lo", "ber_lo_snr", "snr_hi", "ber_hi_snr",
             "decades_dropped"], floors)
    run.csv("results_m2.csv", FIELDS, [{k: r[k] for k in FIELDS} for r in rows])

    print("\n=== 全網格：相對未量化浮點（4.137 dB）的損失，dB")
    print("                    D=24    D=32    D=48    D=64")
    for Q in QS:
        for clip in CLIPS:
            cells = []
            for D in DS:
                g = [x for x in grid
                     if x["Q"] == Q and x["clip"] == clip and x["D"] == D]
                cells.append(f"{g[0]['loss_vs_float_db']:+6.3f}" if g else "   -  ")
            print(f"  Q={Q} clip={clip}σ: " + "  ".join(cells))

    print("\n=== G6 負向：不安全格點的 BER floor")
    print(f"  對照 —— 安全組態 (Q=4,W=10,D=32) 在 "
          f"{safe_ref[0]['snr_db']}→{safe_ref[-1]['snr_db']} dB 掉了 {ref_dec:.2f} 個數量級")
    for f in floors:
        print(f"  Q={f['Q']} W={f['W']:2d}（不安全）: "
              f"{f['snr_lo']} dB {f['ber_lo_snr']:.2e} → "
              f"{f['snr_hi']} dB {f['ber_hi_snr']:.2e}   "
              f"只掉 {f['decades_dropped']:.2f} 個數量級")

    print("\n=== Winner 組態")
    for w in winners:
        print(f"  Q={w['Q']} clip={w['clip']}σ W={w['W']} D={w['D']:2d}  →  "
              f"{w['required_ebn0_db']:.3f} dB（損失 {w['loss_vs_float_db']:+.3f}），"
              f"survivor {w['survivor_bits']} bits")
        print(f"      理由：{w['rationale']}")

    return run.finalize()


if __name__ == "__main__":
    sys.exit(main())
