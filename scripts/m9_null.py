"""m9_null.py — 同一個 SNR 的獨立重複，建立功耗的 null 分布。

## 為什麼非做不可

`docs/report.md` §4 說「總功耗在 1→5 dB 只變動 1.0%，那是雜訊」。
但 M5 的證據撐不住「那是雜訊」這句話：

    M5-2 的收斂測試跑的是 1 / 2 / 3 個 frame ——**改變的是同一段激勵的長度**，
    不是獨立重複。它證明的是「平均值已經收斂」，不是「重跑一次會差多少」。

沒有 null 分布，跨 SNR 的 1.0% 就沒有東西可以比。`docs/lowpower_baseline.md` §3
因此把它列為套用 2% 門檻的**前提**。

## 做法

同一個組態、**同一個 SNR（3 dB）**、8 個獨立的激勵 seed，其餘一切相同。
量到的散布就是「只有隨機資料改變時，功耗會變多少」——那就是 null。

## 判準（統計上正確的版本）

跨 SNR 的 5 個點各自也帶著一份 seed 雜訊，所以不能拿「跨 SNR 全距」直接對「null 全距」比。
正確做法是檢定**斜率**：

    σ_slope = σ_null / sqrt(Sxx)  ，  Sxx = Σ(x − x̄)² = 10（x = 1..5 dB）
    t = slope / σ_slope

`|t| < 2` ⇒ 斜率與零無法區分 ⇒ 「功耗隨 SNR 變」這句話沒有證據。
這比 R² 可靠得多：R² 只描述 5 個點貼線的程度，**完全不知道量測本身有多吵**
（實測 B0 的 R² = 0.478、B0′ = 0.551 —— 同一個設計、同一組激勵就跨過了 0.5 門檻）。
"""

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ppa.run_power import point  # noqa: E402
from scripts.gates import DATA  # noqa: E402

CONFIG = (4, 10, 64, 2.5)      # 與主掃描同一個組態
SNR_FIXED = 3.0
SEEDS = [20260801, 20260802, 20260803, 20260804,
         20260805, 20260806, 20260807, 20260808]
VARIANTS = ["_rtlv", "_cg_rtlv"]      # B0′ 控制組 / B1′ 最佳化
SXX = 10.0                             # Σ(x−x̄)² for x = 1,2,3,4,5

# 16 個閘級點，每點 2–4 分鐘。用光預算就乾淨結束並回傳 1，由 until 迴圈續跑
# （比照 ppa/run_power.py 與 scripts/m9_sweep.py）。**半份 null 分布不寫檔**：
# 少幾個 seed 的 σ_null 照樣算得出數字，而那個數字會被當成雜訊地板用掉。
# 從環境變數讀，理由同 m9_sweep.py：續跑路徑要能用小預算便宜地測試。
BUDGET_S = float(os.environ.get("BUDGET", "460"))


def main():
    t_start = time.time()
    Q, W, D, clip = CONFIG
    out = {}
    for var in VARIANTS:
        rows = []
        print(f"\n=== null 分布：Q{Q}_W{W}_D{D}{var} @ {SNR_FIXED} dB，"
              f"{len(SEEDS)} 個獨立 seed")
        for sd in SEEDS:
            if time.time() - t_start > BUDGET_S:
                print("時間預算用盡，乾淨結束。再跑一次即可續做。")
                return 1
            t0 = time.time()
            r = point(Q, W, D, clip, SNR_FIXED, variant=var, seed=sd)
            rows.append(r)
            print(f"  seed={sd}  P={r['p_total_w'] * 1e3:8.4f} mW  "
                  f"annot={r['annot_pct']:.1f}%  ({time.time() - t0:.0f}s)",
                  flush=True)
        p = [r["p_total_w"] * 1e3 for r in rows]
        out[var] = {"seeds": SEEDS, "p_mw": p,
                    "mean": statistics.mean(p),
                    "sd": statistics.stdev(p),
                    "range_pct": 100.0 * (max(p) - min(p)) / max(p)}
        print(f"  -> 平均 {out[var]['mean']:.4f} mW   "
              f"σ_null = {out[var]['sd']:.4f} mW   "
              f"全距 {out[var]['range_pct']:.3f}%")

    path = os.path.join(DATA, "power_m9_null.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
