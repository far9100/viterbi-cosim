"""energy_model.py — 總能量、臨界距離 d*、以及證偽條件的裁決。

**所有常數只從 docs/energy_model.md 來。** 那份文件在任何量測開跑之前就 commit 了
（CLAUDE.md §1.2），所以它的 commit 時間戳可驗證早於本檔的任何輸出。

事前預測寫在 docs/falsification.md，同樣在量測之前 commit。本檔負責裁決它們。
"""

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.gates import DATA  # noqa: E402

# ---- docs/energy_model.md §1 物理常數 ----
K_B = 1.380649e-23        # J/K
T0_K = 290.0              # K
C_LIGHT = 2.99792458e8    # m/s
F_C = 2.4e9               # Hz
LAMBDA = C_LIGHT / F_C    # 0.124913 m
L1 = (4.0 * math.pi / LAMBDA) ** 2      # 1 m 處的路徑損耗 = 1.01174e4

# ---- docs/energy_model.md §2 系統參數 ----
NF_DB = 6.0               # 接收機雜訊指數（預設）
N0 = K_B * T0_K * (10.0 ** (NF_DB / 10.0))      # 1.5940e-20 J
ETA_PA = [0.1, 0.5]       # PA 效率的掃描範圍
N_PATHLOSS = {"free_space": 2.0, "indoor": 3.5}
R_SYM = 1e6               # 符號率 1 Msym/s（固定符號率 —— 模型 B 的關鍵假設）
P_CIRCUIT = 60e-3         # P_ct + P_cr = 60 mW
F_CLK = 100e6             # 解碼器時脈
TARGET_BER = 1e-5

# 未編碼 BPSK @ 1e-5（M1 實測 9.571 dB；閉式解 9.588）
EBN0_UNCODED_DB = 9.571

# ---- docs/energy_model.md §6.2 ADC 能量（**敏感度線，不是量測值**）----
#
# Walden FoM：   E_conv = FoM · 2^ENOB   （每次轉換的能量）
#
# 一個 R=1/2 的碼，每個 **info bit** 要 2 個 coded bit ⇒ **2 次轉換**：
#
#     E_ADC / info bit = 2 · FoM · 2^Q
#
# 為什麼一定要放進來（docs/energy_model.md §6.2 已經承諾了）：
# 頭條圖是「d* vs Q」，而 E_ADC ∝ 2^Q —— 排除它會**系統性低估大 Q 的代價**。
# Q: 3 -> 6 時 E_ADC 增加 **8 倍**，方向與 E_dec 相同，所以它只會**加大** Δd*。
#
# FoM 的範圍：state-of-the-art 的 SAR ADC 約 5–10 fJ/conv-step；
# 實務上的中階設計 100 fJ；較舊或高速的 flash 可到 500 fJ 以上。三個都掃，如實並陳。
# **未編碼鏈路的 1-bit slicer 只需 1 次比較，其能量可忽略（見 docs/energy_model.md §6.3）。**
ADC_FOM_J = [10e-15, 100e-15, 500e-15]     # J / conversion-step
ADC_FOM_DEFAULT = 100e-15


def e_adc(Q, fom_j=ADC_FOM_DEFAULT, rate_inv=2):
    """每個 info bit 的 ADC 能量（J）。rate_inv = 1/R = 2（R=1/2 ⇒ 每 info bit 2 次轉換）。"""
    return rate_inv * fom_j * (2.0 ** Q)


def d_star(ebn0_coded_db, e_dec_j, eta, n, model, e_adc_j=0.0):
    """臨界距離：低於它，未編碼的每交付位元總能量反而較低。

        d*^n = [ E_dec + E_ADC + ΔE_circ ] · η / [ ΔEbN0 · N0 · L1 ]

    模型 A：ΔE_circ = 0（只算 PA + 解碼器，規格書 §7 原樣）
    模型 B：ΔE_circ = P_circuit / R_sym
            R=1/2 在**固定符號率**下要花兩倍空中時間，所以編碼鏈路多付一份電路能量。

    e_adc_j：每 info bit 的 ADC 能量。**預設 0**，讓主結果與預先登記的模型完全一致；
             ADC 只作為 §6.2 承諾的**敏感度線**加上去，不混進主數字。
    """
    ebn0_u = 10.0 ** (EBN0_UNCODED_DB / 10.0)
    ebn0_c = 10.0 ** (ebn0_coded_db / 10.0)
    d_ebn0 = ebn0_u - ebn0_c                     # 線性差
    if d_ebn0 <= 0:
        return float("nan")

    e_circ = 0.0 if model == "A" else P_CIRCUIT / R_SYM
    num = (e_dec_j + e_adc_j + e_circ) * eta
    den = d_ebn0 * N0 * L1
    return (num / den) ** (1.0 / n)


def main():
    with open(os.path.join(DATA, "power.json")) as f:
        pw = json.load(f)
    pts = pw["points"]

    with open(os.path.join(DATA, "m2_winners.csv")) as f:
        pass  # winner 的所需 Eb/N0 從 m2_grid 取

    import csv
    grid = {}
    with open(os.path.join(DATA, "m2_grid.csv")) as f:
        for r in csv.DictReader(f):
            grid[(int(r["Q"]), float(r["clip"]), int(r["D"]))] = \
                float(r["required_ebn0_db"])

    # 每個 winner 組態：取 3 dB 那個點的功耗（SNR 依賴另外分析）
    rows = []
    for p in pts:
        if p["snr_db"] != 3.0:
            continue
        Q, W, D, clip = p["Q"], p["W"], p["D"], p["clip"]
        req = grid.get((Q, clip, D))
        if req is None:
            continue

        # E_dec = P / f_clk（full-parallel 為 1 info bit/cycle）
        e_dec = p["p_total_w"] / F_CLK
        e_dyn = (p["p_total_w"] - p["p_total_leak_w"]) / F_CLK
        p_leak = p["p_total_leak_w"]

        row = {"Q": Q, "W": W, "D": D, "clip": clip,
               "required_ebn0_db": req,
               "p_total_w": p["p_total_w"],
               "e_dec_pj_per_bit": e_dec * 1e12,
               "e_dyn_pj_per_bit": e_dyn * 1e12,
               "p_leak_w": p_leak}
        for model in ("A", "B"):
            for env, n in N_PATHLOSS.items():
                for eta in ETA_PA:
                    row[f"dstar_{model}_{env}_eta{eta}_m"] = \
                        d_star(req, e_dec, eta, n, model)
        rows.append(row)

    return rows, grid


if __name__ == "__main__":
    rows, grid = main()
    print("=== 常數（來自 docs/energy_model.md，量測前已 commit）")
    print(f"  N0 = k·T0·F = {N0:.4e} J   (NF = {NF_DB} dB)")
    print(f"  L(1 m) = {L1:.4e}          (2.4 GHz 自由空間)")
    print(f"  未編碼 @1e-5 = {EBN0_UNCODED_DB} dB   (M1 實測)")
    print()
    print("=== 每個 winner 組態")
    for r in rows:
        print(f"  Q={r['Q']} W={r['W']:2d} D={r['D']:2d} clip={r['clip']}σ")
        print(f"    所需 Eb/N0  {r['required_ebn0_db']:.3f} dB")
        print(f"    P_total     {r['p_total_w']*1e3:.2f} mW @ 100 MHz")
        print(f"    E_dec       {r['e_dec_pj_per_bit']:.0f} pJ/info-bit")
        for model in ("A", "B"):
            s = "  ".join(
                f"{env}/η={eta}: {r[f'dstar_{model}_{env}_eta{eta}_m']:.1f} m"
                for env in N_PATHLOSS for eta in ETA_PA)
            print(f"    d* 模型{model}   {s}")
        print()
