"""plot_m5.py — M5 的交付圖表。全部由 data/*.csv 重生。

    fig_m5_power_snr.png   功耗 vs SNR，分區塊 —— R1 的裁決
    fig_m5_area.png        面積的分區塊拆解
    fig_m5_dstar.png       E_total vs 距離 d，標出 d*（未編碼 vs 編碼）
    fig_m5_dstar_q.png     頭條圖：d* vs Q
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
from scripts.energy_model import (EBN0_UNCODED_DB, ETA_PA, F_CLK,  # noqa: E402
                                  L1, N0, N_PATHLOSS, P_CIRCUIT, R_SYM)
from scripts.gates import DATA, REPO  # noqa: E402

_CJK = "/mnt/c/Windows/Fonts/NotoSansTC-VF.ttf"
if os.path.exists(_CJK):
    font_manager.fontManager.addfont(_CJK)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=_CJK).get_name()
plt.rcParams["axes.unicode_minus"] = False

FIG = os.path.join(REPO, "figures")
BLOCKS = [("u_tb", "traceback (register exchange)", "tab:red"),
          ("u_acs", "ACS (butterfly + PM 暫存器)", "tab:blue"),
          ("u_minpm", "min-PM argmin 樹", "tab:orange"),
          ("u_bmu", "BMU", "tab:green"),
          ("u_ctrl", "控制 FSM", "tab:grey")]


def load(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


def e_total(d, ebn0_db, e_dec, eta, n, model):
    """每交付位元的總能量（J）。"""
    ebn0 = 10.0 ** (ebn0_db / 10.0)
    e_tx = ebn0 * N0 * L1 * d ** n / eta
    e_circ = 0.0 if model == "A" else P_CIRCUIT / R_SYM
    return e_tx + e_dec + e_circ


def main():
    os.makedirs(FIG, exist_ok=True)
    pw = load("results_m5_power.csv")
    ds = load("results_m5_dstar.csv")

    # ---------- 圖 1：功耗 vs SNR（R1 的裁決）----------
    sweep = sorted([p for p in pw if p["tag"] == "Q4_W10_D64"],
                   key=lambda p: float(p["snr_db"]))
    if len(sweep) >= 3:
        snr = [float(p["snr_db"]) for p in sweep]
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6))

        tot = [float(p["p_total_w"]) * 1e3 for p in sweep]
        ax1.plot(snr, tot, marker="o", color="k", lw=2, label="總功耗")
        for key, lab, col in BLOCKS:
            v = [float(p[f"p_{key}_w"]) * 1e3 for p in sweep]
            if max(v) > 0.01:
                ax1.plot(snr, v, marker="s", ms=4, color=col, label=lab)
        ax1.set_xlabel("Eb/N0 (dB)")
        ax1.set_ylabel("功耗 (mW) @ 100 MHz")
        ax1.set_title("功耗 vs SNR（分區塊）")
        ax1.grid(alpha=0.3)
        ax1.legend(fontsize=8)

        # 右圖：只看 switching（動態、資料相依的那一部分），正規化
        for key, lab, col in BLOCKS[:3]:
            v = np.array([float(p[f"p_{key}_sw_w"]) for p in sweep])
            if v.max() > 0:
                ax2.plot(snr, 100.0 * v / v[0], marker="s", color=col, label=lab)
        vt = np.array([float(p["p_total_w"]) for p in sweep])
        ax2.plot(snr, 100.0 * vt / vt[0], marker="o", color="k", lw=2,
                 label="總功耗")
        ax2.axhline(100, color="grey", lw=0.6)
        # 把「規格書預期的效應」畫出來當對照——它預期低 SNR 功耗高（往左上）
        ax2.set_ylim(95, 105)
        ax2.set_xlabel("Eb/N0 (dB)")
        ax2.set_ylabel("相對 1 dB 的百分比 (%)")
        ax2.set_title("放大來看：全部落在 ±3% 之內")
        ax2.grid(alpha=0.3)
        ax2.legend(fontsize=8)

        tot_var = 100.0 * (max(tot) - min(tot)) / max(tot)
        fig.suptitle(
            f"規格書 §7 的交付物**不存在**：總功耗在 1→5 dB 只變動 {tot_var:.1f}%"
            f"（且非單調 = 雜訊），方向還與規格書的前提相反。\n"
            f"機制見 fig_m5_toggle.png：整條資料路徑的位元活動被隨機資訊源"
            f"釘在最大熵，與 SNR 無關。", fontsize=10)
        fig.tight_layout()
        fig.savefig(os.path.join(FIG, "fig_m5_power_snr.png"), dpi=150)

    # ---------- 圖 1b：機制 —— 這張圖取代那個不存在的交付物 ----------
    tg_path = os.path.join(DATA, "results_m5_toggle.csv")
    mc_path = os.path.join(DATA, "results_m5_mechanism.csv")
    if os.path.exists(tg_path) and os.path.exists(mc_path):
        tg = load("results_m5_toggle.csv")
        mc = load("results_m5_mechanism.csv")

        fig, (bx1, bx2, bx3) = plt.subplots(1, 3, figsize=(16, 4.8))

        # --- 左：gate-level SAIF 的翻轉密度 vs SNR，分訊號 ---
        SIG = [("in_r", "r（通道輸入）", "tab:green"),
               ("bm", "bm（分支度量）", "tab:olive"),
               ("pm", "pm（路徑度量：**累加器**）", "tab:purple"),
               ("surv", "surv（倖存者決策）", "tab:red"),
               ("re", "RE 暫存器（traceback）", "tab:brown")]
        for key, lab, col in SIG:
            pts = sorted([(float(r["snr_db"]), float(r["tc_per_cycle"]))
                          for r in tg if r["tag"] == "Q4_W10_D64"
                          and r["signal"] == key])
            if pts:
                bx1.plot([p[0] for p in pts], [p[1] for p in pts],
                         marker="o", color=col, label=lab,
                         lw=2.5 if key == "pm" else 1.5)
        bx1.axhline(0.5, color="grey", ls=":", lw=1)
        bx1.text(4.9, 0.515, "最大熵 = 擲硬幣", fontsize=8, color="grey", ha="right")
        bx1.set_ylim(0, 0.62)
        bx1.set_xlabel("Eb/N0 (dB)")
        bx1.set_ylabel("翻轉密度（次 / net / cycle）")
        bx1.set_title("gate-level SAIF：整條資料路徑\n"
                      "唯一不在最大熵的是 pm（累加器）")
        bx1.grid(alpha=0.3)
        bx1.legend(fontsize=7.5, loc="lower right")

        # --- 中：正規化，看誰真的隨 SNR 動 ---
        for key, lab, col in SIG:
            pts = sorted([(float(r["snr_db"]), float(r["tc_per_cycle"]))
                          for r in tg if r["tag"] == "Q4_W10_D64"
                          and r["signal"] == key])
            if pts:
                base = pts[0][1]
                bx2.plot([p[0] for p in pts], [100 * p[1] / base for p in pts],
                         marker="o", color=col, label=lab,
                         lw=2.5 if key == "pm" else 1.5)
        bx2.axhline(100, color="grey", lw=0.8)
        bx2.set_xlabel("Eb/N0 (dB)")
        bx2.set_ylabel("相對 1 dB (%)")
        bx2.set_title("只有 pm 隨 SNR 單調上升（+3.3%）\n"
                      "其餘全是雜訊 —— 這就是功耗平掉的原因")
        bx2.grid(alpha=0.3)
        bx2.legend(fontsize=7.5)

        # --- 右：反事實 —— 打破量化器的位元互補性，效應就回來了 ---
        sym = [r for r in mc if r["case"] == "fixed_hi_sym"]
        asym = [r for r in mc if r["case"] == "fixed_hi_asym"]
        if sym and asym:
            Qb = 4
            x = np.arange(Qb)
            vs = [float(sym[0][f"tog_r_b{k}"]) for k in range(Qb)]
            va = [float(asym[0][f"tog_r_b{k}"]) for k in range(Qb)]
            bx3.bar(x - 0.19, vs, 0.36, label="對稱量化器（本專案）：r1 = ~r0，位元互補",
                    color="tab:blue")
            bx3.bar(x + 0.19, va, 0.36,
                    label="ADC 有 DC 偏移：r1 ≠ ~r0，對稱性被打破",
                    color="tab:orange")
            bx3.axhline(0.5, color="grey", ls=":", lw=1)
            # **零高度的長條看起來像「資料不見了」，必須明確標值**，
            # 否則讀者無法分辨「量到 0」與「沒量」。
            for k in range(Qb):
                bx3.text(k - 0.19, vs[k] + 0.012, f"{vs[k]:.3f}", ha="center",
                         fontsize=7.5, color="tab:blue")
                zero = va[k] < 0.05
                bx3.text(k + 0.19, va[k] + 0.012,
                         f"{va[k]:.3f}" + ("\n← 崩了" if zero else ""),
                         ha="center", fontsize=7.5,
                         color="tab:orange",
                         fontweight="bold" if zero else "normal")
            bx3.set_xticks(x)
            bx3.set_xticklabels(
                [f"bit{k}\n{'兩 rail 相同' if va[k] < 0.05 else '兩 rail 相異'}"
                 for k in range(Qb)], fontsize=8)
            bx3.set_ylim(0, 0.62)
            bx3.set_ylabel("r 的逐位元翻轉率")
            bx3.set_xlabel("量化器輸出的位元位置（30 dB，幾乎無雜訊）")
            bx3.set_title("反事實：把對稱性打破，效應就回來了\n"
                          "定律 toggle(k) = 0.5 · 1{bit k 在兩個 rail 上相異}")
            bx3.grid(alpha=0.3, axis="y")
            bx3.legend(fontsize=7.5, loc="upper center")

        fig.suptitle(
            "為什麼「功耗 vs SNR」不存在：BPSK 的兩個假設被對稱量化器映到**位元互補**的碼"
            "（r1 = ~r0），\n而編碼位元是 i.i.d. uniform ⇒ r 的每個位元在任何 SNR 下都以 0.5 翻轉。"
            "倖存者位元同理（它就是 u[t−6]）。SNR 只改變**正確性**，改變不了**統計**。",
            fontsize=10)
        fig.tight_layout()
        fig.savefig(os.path.join(FIG, "fig_m5_toggle.png"), dpi=150)

    # ---------- 圖 2：E_total vs 距離 ----------
    at3 = {(int(p["Q"]), int(p["D"])): p for p in pw
           if float(p["snr_db"]) == 3.0}
    req = {(int(r["Q"]), int(r["D"])): float(r["required_ebn0_db"]) for r in ds}

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for ax, model in zip(axes, ("A", "B")):
        d = np.logspace(-0.5, 3.5, 300)
        eta, n = 0.1, N_PATHLOSS["indoor"]

        # 未編碼：沒有解碼器，airtime 只有一半（固定符號率）
        e_u = (10 ** (EBN0_UNCODED_DB / 10) * N0 * L1 * d ** n / eta
               + (0.0 if model == "A" else P_CIRCUIT / R_SYM / 2.0))
        ax.loglog(d, e_u * 1e9, "k--", lw=2, label="未編碼 BPSK")

        for (Q, D), col in zip(sorted(at3), ("tab:green", "tab:blue",
                                             "tab:orange", "tab:red")):
            p = at3[(Q, D)]
            e_dec = float(p["p_total_w"]) / F_CLK
            e_c = e_total(d, req[(Q, D)], e_dec, eta, n, model)
            ax.loglog(d, e_c * 1e9, color=col, label=f"K=7  Q={Q}, D={D}")

            # d*：兩條曲線相交處
            k = np.argmin(np.abs(e_c - e_u))
            ax.plot(d[k], e_c[k] * 1e9, "o", color=col, ms=7)

        ax.set_xlabel("距離 d (m)")
        ax.set_ylabel("每交付位元的總能量 (nJ)")
        ax.set_title(f"模型 {model}"
                     + ("（僅 PA + 解碼器）" if model == "A"
                        else "（+ 收發電路 + 2× airtime）"))
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=8)
    fig.suptitle("E_total vs 距離：圓點是臨界距離 d*"
                 "（室內 n=3.5, η_PA=0.1, NF=6 dB）", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_m5_dstar.png"), dpi=150)

    # ---------- 圖 3：頭條圖 —— d* vs Q ----------
    fig, ax = plt.subplots(figsize=(7, 5))
    for model, ls in (("A", "-"), ("B", "--")):
        for env, col in (("indoor", "tab:blue"), ("free_space", "tab:red")):
            pts = sorted([(int(r["Q"]), float(r["dstar_m"])) for r in ds
                          if r["model"] == model and r["env"] == env
                          and float(r["eta_pa"]) == 0.1 and int(r["D"]) == 32])
            if len(pts) >= 2:
                q = [p[0] for p in pts]
                v = [p[1] for p in pts]
                base = v[0]
                ax.plot(q, [100.0 * x / base for x in v], marker="o", ls=ls,
                        color=col,
                        label=f"模型{model} / {'室內' if env=='indoor' else '自由空間'}")
    ax.axhline(100, color="grey", lw=0.8)
    ax.set_xlabel("軟判決位元數 Q（D=32 固定 —— traceback 完全相同）")
    ax.set_ylabel("d* 相對 Q=3 的百分比 (%)")
    ax.set_title("頭條圖：字寬如何移動臨界距離 d*")
    ax.set_xticks([3, 6])
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_m5_dstar_q.png"), dpi=150)

    print(f"圖已寫入 {FIG}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
