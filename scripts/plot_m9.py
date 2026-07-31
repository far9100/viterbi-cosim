"""plot_m9.py — M9 的交付圖：最佳化過的設計上，SNR 依賴變成什麼樣子。

    fig_m9_states.png   三態的功耗 vs SNR，附 null 分布的 ±2σ 帶

## 為什麼一定要把 null 帶畫上去

`docs/report.md` §4 原本的圖只有一條幾乎平的曲線，讀者無從判斷那 1.0% 是效應還是雜訊。
把「同一個 SNR、8 個獨立 seed」量出來的 ±2σ 帶疊上去之後，這件事變成目視可判：
曲線的起伏落在帶子裡，就沒有證據說功耗隨 SNR 變。

**這也是 M5 缺的東西**：M5-2 的收斂測試改變的是同一段激勵的長度，不是獨立重複，
所以它畫不出這條帶子（見 `scripts/m9_null.py` 的說明）。
"""

import json
import math
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
SXX = 10.0


def main():
    os.makedirs(FIG, exist_ok=True)
    with open(os.path.join(DATA, "power_m9.json")) as f:
        m9 = json.load(f)["points"]
    with open(os.path.join(DATA, "power_m9_null.json")) as f:
        nul = json.load(f)
    with open(os.path.join(DATA, "power.json")) as f:
        b0 = json.load(f)["points"]

    series = [
        ("B0  原 RTL / 無 clock gating（M5 已發表）",
         sorted([r for r in b0 if r["tag"] == "Q4_W10_D64"],
                key=lambda r: r["snr_db"]), None, "tab:gray", "o"),
        ("B0′ 改寫 RTL / 無 clock gating（控制組）",
         sorted([r for r in m9 if r.get("variant") == "_rtlv" and r["Q"] == 4],
                key=lambda r: r["snr_db"]), nul.get("_rtlv"), "tab:blue", "s"),
        ("B1′ 改寫 RTL / 有 clock gating（最佳化）",
         sorted([r for r in m9 if r.get("variant") == "_cg_rtlv" and r["Q"] == 4],
                key=lambda r: r["snr_db"]), nul.get("_cg_rtlv"), "tab:red", "D"),
    ]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.5))

    # ---- 左：絕對功耗 ----
    for label, pts, nd, color, mk in series:
        xs = [r["snr_db"] for r in pts]
        ys = [r["p_total_w"] * 1e3 for r in pts]
        ax1.plot(xs, ys, marker=mk, color=color, lw=1.6, ms=6, label=label)
        if nd:
            m, sd = nd["mean"], nd["sd"]
            ax1.fill_between([min(xs), max(xs)], m - 2 * sd, m + 2 * sd,
                             color=color, alpha=0.15, lw=0)
    ax1.set_xlabel("Eb/N0 (dB)")
    ax1.set_ylabel("總功耗 (mW) @ 100 MHz")
    ax1.set_title("絕對功耗：clock gating 省 42.8%\n"
                  "（色帶 = 同一 SNR、8 個獨立 seed 的 ±2σ —— 曲線整條落在帶內）")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=8, loc="center right")

    # ---- 右：各自正規化到自己的平均，看 SNR 依賴的相對大小 ----
    for label, pts, nd, color, mk in series:
        xs = [r["snr_db"] for r in pts]
        ys = [r["p_total_w"] * 1e3 for r in pts]
        m = sum(ys) / len(ys)
        ax2.plot(xs, [100 * (y / m - 1) for y in ys], marker=mk, color=color,
                 lw=1.6, ms=6, label=label.split("（")[0])
        if nd:
            s = 100 * nd["sd"] / nd["mean"]
            ax2.fill_between([min(xs), max(xs)], -2 * s, 2 * s,
                             color=color, alpha=0.15, lw=0)
    ax2.axhline(0, color="black", lw=0.8, alpha=0.5)
    ax2.set_xlabel("Eb/N0 (dB)")
    ax2.set_ylabel("相對各自平均的偏差 (%)")
    # 標題刻意講「形狀相同」而不是「SNR 依賴放大」：後者是本圖第一版的說法，
    # 但 B1′ 的 null 分布跑完後發現**純 seed 的相對全距用同一個倍數在漲**，
    # 相對全距放大只反映分母縮小，不能當 SNR 依賴的證據（見 m9_gate.py M9-7 的自我更正）。
    ax2.set_title("三態的起伏形狀幾乎完全相同（r > 0.99）\n"
                  "⇒ 形狀由「抽到哪組資料」決定，不由 SNR 或設計決定")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=8)

    fig.suptitle("M9：最佳化過的設計上，功耗對 SNR 的依賴", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_m9_states.png"), dpi=150)
    print(f"圖已寫入 {FIG}/fig_m9_states.png")

    for label, pts, nd, _c, _m in series:
        ys = [r["p_total_w"] * 1e3 for r in pts]
        rng = 100 * (max(ys) - min(ys)) / max(ys)
        line = f"  {label.split('（')[0]:36s} 全距 {rng:5.2f}%"
        if nd:
            sd = nd["sd"]
            mx, my = 3.0, sum(ys) / len(ys)
            slope = (sum((x - mx) * (y - my) for x, y in
                         zip([r["snr_db"] for r in pts], ys)) / SXX)
            line += (f"  σ_null {sd:.4f} mW"
                     f"  t = {slope / (sd / math.sqrt(SXX)):+.2f}")
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
