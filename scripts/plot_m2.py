"""plot_m2.py — M2 的交付圖表，全部由 data/*.csv 重生。

    fig_m2_grid.png       設計空間：所需 Eb/N0 vs D，每條線一個 Q（取各 Q 的最佳 clip）
    fig_m2_ber_floor.png  G6 的負向展示：不安全格點的 BER 不但沒有隨 SNR 下降，反而變差
"""

import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.gates import DATA, REPO  # noqa: E402

_CJK = "/mnt/c/Windows/Fonts/NotoSansTC-VF.ttf"
if os.path.exists(_CJK):
    font_manager.fontManager.addfont(_CJK)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=_CJK).get_name()
plt.rcParams["axes.unicode_minus"] = False

FIG = os.path.join(REPO, "figures")
REQ_FS = 4.137


def load(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


def main():
    os.makedirs(FIG, exist_ok=True)
    grid = load("m2_grid.csv")
    res = load("results_m2.csv")

    # ---------- 圖 1：設計空間 ----------
    fig, ax = plt.subplots(figsize=(7, 5))
    for Q, col in zip((3, 4, 5, 6), ("tab:green", "tab:blue", "tab:orange", "tab:red")):
        # 每個 (Q, D) 取最佳 clip —— clip 是可以自由調的，不是硬體成本
        pts = []
        for D in (24, 32, 48, 64):
            cand = [float(g["loss_vs_float_db"]) for g in grid
                    if int(g["Q"]) == Q and int(g["D"]) == D]
            if cand:
                pts.append((D, min(cand)))
        ax.plot([p[0] for p in pts], [p[1] for p in pts],
                marker="o", color=col, label=f"Q={Q}（W={8 if Q==3 else (10 if Q<=5 else 12)}）")

    ax.axvline(35, color="grey", ls="--", lw=0.8)
    ax.text(35.6, 0.45, "5K = 35\n（理論下限）", fontsize=8, color="grey")
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xlabel("回溯深度 D（survivor 記憶體 = 64×3D 位元，支配面積）")
    ax.set_ylabel("相對未量化浮點的損失 (dB)")
    ax.set_title("M2 設計空間：每個 (Q, D) 取最佳 clip")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_m2_grid.png"), dpi=150)

    # ---------- 圖 2：BER floor ----------
    fig, ax = plt.subplots(figsize=(7, 5))

    safe = sorted([r for r in res if int(r["Q"]) == 4 and int(r["W"]) == 10
                   and int(r["D"]) == 32 and float(r["clip"]) == 2.0],
                  key=lambda r: float(r["snr_db"]))
    ax.plot([float(r["snr_db"]) for r in safe], [float(r["ber"]) for r in safe],
            marker="o", color="tab:blue", lw=2,
            label="安全格點 Q=4, W=10（正常）")

    styles = {(4, 8): "tab:red", (5, 8): "tab:orange",
              (6, 8): "tab:purple", (6, 10): "tab:brown"}
    for (Q, W), col in styles.items():
        c = sorted([r for r in res if int(r["Q"]) == Q and int(r["W"]) == W
                    and int(r["D"]) == 32],
                   key=lambda r: float(r["snr_db"]))
        if not c:
            continue
        ax.plot([float(r["snr_db"]) for r in c], [float(r["ber"]) for r in c],
                marker="x", ls="--", color=col,
                label=f"不安全 Q={Q}, W={W}（2^(W-1)={1 << (W-1)}）")

    ax.axhline(0.5, color="grey", lw=0.8, ls=":")
    ax.text(2.1, 0.55, "BER = 0.5（等同擲硬幣）", fontsize=8, color="grey")
    ax.set_yscale("log")
    ax.set_xlabel("Eb/N0 (dB)")
    ax.set_ylabel("BER")
    ax.set_title("G6 的負向展示：字寬不足時，BER 不降反升")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8, loc="center right")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_m2_ber_floor.png"), dpi=150)

    print(f"兩張圖已寫入 {FIG}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
