"""plot_m1.py — M1 的交付圖表。全部由 data/*.csv 重生，不手繪（CLAUDE.md §5.4）。

    fig_ber_m1.png       BER vs Eb/N0：未編碼 / 浮點軟 / 浮點硬 / 定點各 Q
    fig_c1_loss.png      C1：量化損失 dB vs Q，每條線一個 clip level
    fig_d_sweep.png      windowed(D) 相對全幀 ML 的損失
"""

import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402

# 中文字型：matplotlib 內建的 DejaVu Sans 沒有 CJK 字符，圖上的中文會變成豆腐方塊。
# WSL 讀得到 Windows 的字型目錄，直接借用 Noto Sans TC（繁體）。
# 不用 apt 裝字型的理由：這台機器的 sudo 需要密碼，agent 不能非互動地跑 apt。
_CJK = "/mnt/c/Windows/Fonts/NotoSansTC-VF.ttf"
if os.path.exists(_CJK):
    font_manager.fontManager.addfont(_CJK)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=_CJK).get_name()
plt.rcParams["axes.unicode_minus"] = False   # 用 ASCII 的減號，避免 U+2212 也變豆腐

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate  # noqa: E402
from golden.bounds import union_bound_ber, weight_spectrum  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from scripts.gates import DATA, REPO  # noqa: E402

FIG = os.path.join(REPO, "figures")


def load(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


def curve(rows, cfg):
    c = [r for r in rows if r["config"] == cfg]
    c.sort(key=lambda r: float(r["ebn0_db"]))
    return (np.array([float(r["ebn0_db"]) for r in c]),
            np.array([float(r["ber"]) for r in c]),
            np.array([float(r["ci_low"]) for r in c]),
            np.array([float(r["ci_high"]) for r in c]))


def main():
    os.makedirs(FIG, exist_ok=True)
    rows = load("results_m1.csv")
    t = viterbi_trellis()
    R = code_rate(1024, t.m)
    _, c_spec = weight_spectrum(t, d_max=30)   # 收斂值，見 diag_bound_conv.py

    # ---------- 圖 1：BER 曲線 ----------
    fig, ax = plt.subplots(figsize=(7.5, 5.5))

    for cfg, label, style in [
        ("uncoded", "未編碼 BPSK", dict(color="k", marker="s", ls="--")),
        ("float_hard_D64", "K=7 硬判決 (D=64)", dict(color="tab:orange", marker="^")),
        ("float_soft_D64", "K=7 軟判決, 未量化 (D=64)", dict(color="tab:blue", marker="o")),
    ]:
        e, b, lo, hi = curve(rows, cfg)
        if len(e) == 0:
            continue
        # 信賴區間用 cluster-robust（Viterbi 的錯誤成叢，Wilson 會把區間畫得太窄）
        ax.errorbar(e, b, yerr=[np.maximum(b - lo, 0), np.maximum(hi - b, 0)],
                    label=label, capsize=3, **style)

    for Q, col in zip((3, 6), ("tab:green", "tab:red")):
        e, b, lo, hi = curve(rows, f"fx_Q{Q}_clip2.0")
        if len(e):
            ax.errorbar(e, b, yerr=[np.maximum(b - lo, 0), np.maximum(hi - b, 0)],
                        label=f"定點 Q={Q}, clip=2.0σ (W=12, D=64)",
                        color=col, marker="d", ls=":", capsize=3)

    eb = np.linspace(1.5, 5.5, 60)
    ax.plot(eb, union_bound_ber(eb, c_spec, R, 10), color="tab:blue", lw=1,
            ls="-.", alpha=0.6, label="union bound (133,171)")

    ax.axhline(1e-5, color="grey", lw=0.8, alpha=0.5)
    ax.set_yscale("log")
    ax.set_xlabel("Eb/N0 (dB)")
    ax.set_ylabel("BER")
    ax.set_ylim(1e-7, 0.5)
    ax.set_title("M1：K=7 (133,171) R=1/2 —— BER vs Eb/N0")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_ber_m1.png"), dpi=150)

    # ---------- 圖 2：C1 量化損失 ----------
    c1 = load("c1_quantization_loss.csv")
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for clip in sorted({float(r["clip"]) for r in c1}):
        pts = sorted((int(r["Q"]), float(r["loss_db"]))
                     for r in c1 if float(r["clip"]) == clip)
        ax.plot([p[0] for p in pts], [p[1] for p in pts],
                marker="o", label=f"clip = {clip}σ")
    ax.axhline(0.2, color="grey", ls="--", lw=0.8)
    ax.text(5.6, 0.21, "G3: 0.2 dB", fontsize=8, color="grey")
    ax.set_xlabel("軟判決位元數 Q")
    ax.set_ylabel("相對未量化的損失 (dB)")
    ax.set_xticks([3, 4, 5, 6])
    ax.set_title("C1：量化損失 vs 字寬與 clip level（W=12, D=64）")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_c1_loss.png"), dpi=150)

    # ---------- 圖 3：D 軸 ----------
    ds = load("d_sweep.csv")
    fig, ax = plt.subplots(figsize=(6, 4))
    D = [int(r["D"]) for r in ds]
    L = [float(r["loss_vs_ml_db"]) for r in ds]
    ax.plot(D, L, marker="o", color="tab:purple")
    ax.axvline(35, color="grey", ls="--", lw=0.8)
    ax.text(35.5, max(L) * 0.8, "5K = 35\n（理論下限）", fontsize=8, color="grey")
    ax.set_xlabel("回溯深度 D")
    ax.set_ylabel("相對全幀 ML 的損失 (dB)")
    ax.set_title("D 軸：sliding window 的深度代價")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_d_sweep.png"), dpi=150)

    print(f"三張圖已寫入 {FIG}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
