"""plot_pareto.py — 規格書 §9 M6 驗收條件的「與既有通訊模擬器的 Pareto 前緣圖接上」。

    fig_pareto.png   通訊效能（所需 Eb/N0）× 硬體成本，含 Pareto 前緣

## 為什麼補這張圖

規格書 §9 的 M6 驗收條件明列這一項，但 M6 從未產出它，也**從未記為未做**——
全 repo 搜尋 `pareto` 只命中規格書那一行。這是唯一一項被靜默放掉的驗收條件。

## 為什麼硬體軸有兩條，而不是只畫 E_dec

**只有 4 個組態被合成過。** 64 個網格點裡有 60 個沒有任何量到的硬體數字。
如果只用 E_dec 當 y 軸，這張圖就只剩 4 個點，畫不出前緣，也接不上通訊模擬器那一側。

所以分成兩層，並在圖上明確標示哪一層是量測、哪一層是代理指標：

  * **代理成本（全部 64 點）**：survivor 記憶體 = 64 × 3D 位元。它只與 D 有關，
    不必合成就能算，而 M0 的煙霧測試與計畫的風險 R1 都指出它支配面積。
    用它畫出的前緣是**整個設計空間**的前緣。
  * **量測成本（4 點）**：E_dec，來自真實通道驅動的 gate-level SAIF。疊在同一張圖上，
    讓讀者看到「代理指標與量測值排序是否一致」——這正是代理指標唯一需要被檢驗的事。

**誠實標示**：代理軸不是能量。它是面積的代理，而面積與能量在本設計裡並非同一件事
（report.md §2.1：traceback 佔 67.7–84.1% 的 flop 卻只佔 43.0–54.2% 的功耗）。
圖例與標題都寫明這一點，不讓讀者把兩條軸混為一談。
"""

import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.gates import DATA, REPO  # noqa: E402

_CJK = "/mnt/c/Windows/Fonts/NotoSansTC-VF.ttf"
if os.path.exists(_CJK):
    font_manager.fontManager.addfont(_CJK)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=_CJK).get_name()
plt.rcParams["axes.unicode_minus"] = False

FIG = os.path.join(REPO, "figures")


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pareto_front(points):
    """(x, y) 皆為**越小越好**時的 Pareto 前緣，依 x 排序回傳。"""
    pts = sorted(points, key=lambda p: (p[0], p[1]))
    front, best_y = [], float("inf")
    for x, y, *rest in pts:
        if y < best_y:
            front.append((x, y, *rest))
            best_y = y
    return front


def main():
    os.makedirs(FIG, exist_ok=True)
    grid = load("m2_grid.csv")
    res = {(int(r["Q"]), int(r["D"])): r
           for r in load("results.csv") if float(r["snr_db"]) == 3.0}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # ---- 左：代理成本（全部 64 個網格點）----
    pts = [(float(g["required_ebn0_db"]), 64 * 3 * int(g["D"]),
            int(g["Q"]), int(g["D"]), float(g["clip"]),
            float(g["required_sigma_db"]) if g.get("required_sigma_db") else 0.0)
           for g in grid]
    for Q, color in zip((3, 4, 5, 6), ("tab:blue", "tab:orange",
                                       "tab:green", "tab:red")):
        sub = [p for p in pts if p[2] == Q]
        ax1.errorbar([p[0] for p in sub], [p[1] for p in sub],
                     xerr=[1.96 * p[5] for p in sub], fmt="o", ms=5,
                     color=color, alpha=0.65, elinewidth=0.8, capsize=2,
                     label=f"Q={Q}")
    front = pareto_front([(p[0], p[1], p[2], p[3]) for p in pts])
    ax1.step([p[0] for p in front], [p[1] for p in front], where="post",
             color="black", lw=1.8, label="Pareto 前緣")
    for x, y, Q, D in front:
        ax1.annotate(f"Q{Q}/D{D}", (x, y), textcoords="offset points",
                     xytext=(6, 5), fontsize=8)
    ax1.set_xlabel("所需 Eb/N0 @ BER=1e-5 (dB)（誤差棒 = 95% CI）")
    ax1.set_ylabel("survivor 記憶體 = 64×3D (bits)　— **面積代理，非能量**")
    ax1.set_title("設計空間全景（64 點）：通訊效能 × 硬體代理成本")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=9)

    # ---- 右：量測成本（僅 4 個合成過的組態）----
    m = [(float(r["required_ebn0_db"]), float(r["e_dec_pj_per_bit"]),
          int(r["Q"]), int(r["D"])) for r in res.values()]
    ax2.scatter([p[0] for p in m], [p[1] for p in m], s=90, color="tab:red",
                zorder=3, label="已合成並量測（4 點）")
    mf = pareto_front(m)
    ax2.step([p[0] for p in mf], [p[1] for p in mf], where="post",
             color="black", lw=1.8, label="Pareto 前緣")
    for x, y, Q, D in m:
        ax2.annotate(f"Q{Q}/D{D}", (x, y), textcoords="offset points",
                     xytext=(7, -4), fontsize=9)
    ax2.set_xlabel("所需 Eb/N0 @ BER=1e-5 (dB)")
    ax2.set_ylabel("E_dec (pJ / info bit)　— gate-level SAIF **量測值**")
    ax2.set_title("僅 4 個組態有量到的能量\n（其餘 60 個網格點未合成，不得外插）")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=9)

    fig.suptitle("Pareto 前緣：通訊效能 vs 硬體成本"
                 "（左＝代理指標涵蓋全設計空間，右＝量測值僅 4 點）", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_pareto.png"), dpi=150)

    print(f"圖已寫入 {FIG}/fig_pareto.png")
    print("  代理前緣（64 點）：" +
          "  ".join(f"Q{Q}/D{D}@{x:.3f}dB" for x, _, Q, D in front))
    print("  量測前緣（4 點）： " +
          "  ".join(f"Q{Q}/D{D}@{x:.3f}dB/{y:.0f}pJ" for x, y, Q, D in mf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
