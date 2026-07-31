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


# ---- docs/energy_model.md §2 宣告過、但 M5 從未跑的兩條掃描 ----
#
# 文件 §2 的表明列「掃描範圍」欄：F ∈ {3, 6, 10} dB、P_circuit ∈ {20, 60, 120} mW。
# M5 只用了預設值（6 dB / 60 mW），兩條掃描從未執行——這是文件承諾與交付之間的缺口。
#
# 為什麼它們重要而不只是形式：
#   * F 直接乘進 N0，而 d*^n ∝ 1/N0 ⇒ d* ∝ F^(−1/n)。接收機雜訊指數在 2.4 GHz 低功耗
#     收發機是 3–10 dB 的實際範圍，不是可以忽略的二階項。
#   * P_circuit 是**模型 B 的支配項**（60 nJ 比 E_dec 大 600 倍），它一動 d*(B) 就整組平移。
NF_SWEEP_DB = [3.0, 6.0, 10.0]
P_CIRCUIT_SWEEP = [20e-3, 60e-3, 120e-3]

R_INFO = R_SYM * 0.5      # R=1/2 ⇒ 資訊率 0.5 Mbps（固定符號率，見 energy_model.md §4）


def n0_of(nf_db):
    return K_B * T0_K * (10.0 ** (nf_db / 10.0))


def e_dec_of(e_dyn_per_bit_j, p_leak_w, f_clk=F_CLK, power_gated=True):
    """docs/energy_model.md §5 的 E_dec 分解，含 power gating 的兩種情境。

    有 gating：閒置時完全斷電 ⇒ 只有作用中的那 1 個 cycle 付漏電
                E_dec = e_dyn + p_leak / f_clk
    無 gating：整個 info bit 週期都在漏 ⇒ 付 1/R_info 秒的漏電
                E_dec = e_dyn + p_leak / R_info

    > **文件 §5 的「灌大約 200 倍」是錯的，此處如實更正。**
    > 200 倍是**漏電那一項**的比值（`(1/R_info) / (1/f_clk)` = 2e-6 / 1e-8 = 200），
    > 不是 E_dec 的比值。而漏電只佔本設計總功耗的 **0.00027%**（64 nW vs 24 mW），
    > 所以 200 倍作用在一個可忽略的項上：**E_dec 實際只變 0.05%，d\\* 只變 0.03%。**
    > 也就是說「解碼器在 frame 之間被 power-gated」這個假設**其實無關緊要**——
    > 這對報告是好消息（少一條 caveat），但文件把量級寫錯了，不能沿用。
    """
    return e_dyn_per_bit_j + p_leak_w / (f_clk if power_gated else R_INFO)


def d_star(ebn0_coded_db, e_dec_j, eta, n, model, e_adc_j=0.0,
           n0=None, p_circuit=None):
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

    # n0 / p_circuit 預設用 docs/energy_model.md §2 的預設值；
    # 傳入時即為該文件同一張表宣告過的掃描範圍（NF_SWEEP_DB / P_CIRCUIT_SWEEP）。
    _n0 = N0 if n0 is None else n0
    _pc = P_CIRCUIT if p_circuit is None else p_circuit
    e_circ = 0.0 if model == "A" else _pc / R_SYM
    num = (e_dec_j + e_adc_j + e_circ) * eta
    den = d_ebn0 * _n0 * L1
    return (num / den) ** (1.0 / n)


# ---- 不確定度傳播 ----
#
# 先前整條鏈路的不確定度**到 BER 表就斷了**：BER 有 cluster-robust CI，但 required_ebn0
# 沒有、d* 沒有、Δd* 也沒有。於是 17.8 m、+11.29%、−0.75% 全是裸點估計——而 −0.75%
# 寫到小數第二位卻不給區間，讀者只能假設它站不住。
#
# 三個來源，方向與性質都不同：
#
#   1. **編碼組態的 required Eb/N0**（σ ≈ 0.021–0.024 dB，見 data/m2_grid.csv）。
#      主要來源，是 4.0/4.5 dB 兩點對數內插的統計誤差。
#   2. **未編碼的 required Eb/N0**（σ 由 data/results_m1.csv 的 CI 傳播而得）。
#      **這是共模項**：它同時進入 Q3 與 Q6 的 d*，在 Δd* 的比值裡大部分（但不完全）相消。
#      所以必須把**同一個**抽樣值餵給兩個組態——各抽各的會**高估** Δd* 的不確定度。
#   3. **E_dec 的重複性**（≈0.2%，M5-2 的 frame 數收斂測試）。給定 SAIF 時 OpenSTA 是
#      確定性的，所以這一項不是統計雜訊而是**量測重複性**，如實標示來源後納入。
#
# 一律用 bootstrap 而非解析偏微分：d_star() 是這裡唯一的真值來源，重抽後直接呼叫它，
# 不可能與它分岔（與 golden/ber.py 的 required_ebn0_ci 同一個理由）。
E_DEC_REPEAT_REL = 0.002         # M5-2：1/2/3 frame 的功耗差 < 0.2%
_CI_SEED = 20260729              # 固定 seed：make repro 要求逐位元組重生

_UNCODED_CI = {}


def uncoded_ebn0_ci():
    """未編碼 BPSK 的 required Eb/N0 與其 σ，由 `data/results_m1.csv` **現算**。

    刻意不寫死一個 σ 常數：CLAUDE.md §5.4 要求報告裡的每個數字都存在於 CSV 且可由
    script 重生。手貼一個 σ 會讓它與 M1 的資料悄悄脫節——而 σ 正是判斷 Δd\\* 站不站得住的
    那個量，脫節的後果比脫節一個 BER 點嚴重。
    """
    if not _UNCODED_CI:
        import csv as _csv

        from golden.ber import required_ebn0_ci
        curve = [{"ebn0_db": float(r["ebn0_db"]), "ber": float(r["ber"]),
                  "ci_low": float(r["ci_low"]), "ci_high": float(r["ci_high"])}
                 for r in _csv.DictReader(
                     open(os.path.join(DATA, "results_m1.csv"), encoding="utf-8"))
                 if r["kind"] == "uncoded"]
        _UNCODED_CI.update(required_ebn0_ci(curve, TARGET_BER))
    return _UNCODED_CI


def _dstar_raw(ebn0_c_db, ebn0_u_db, e_dec_j, eta, n, model):
    gu, gc = 10.0 ** (ebn0_u_db / 10.0), 10.0 ** (ebn0_c_db / 10.0)
    if gu <= gc:
        return None
    e_circ = 0.0 if model == "A" else P_CIRCUIT / R_SYM
    return (((e_dec_j + e_circ) * eta) / ((gu - gc) * N0 * L1)) ** (1.0 / n)


def d_star_ci(ebn0_coded_db, e_dec_j, eta, n, model, sigma_ebn0_db,
              sigma_uncoded_db=None,
              e_dec_rel=E_DEC_REPEAT_REL, n_boot=20000, seed=_CI_SEED):
    """單一組態的 d* 之 1-σ 與 95% 區間。"""
    if sigma_uncoded_db is None:
        sigma_uncoded_db = uncoded_ebn0_ci()["sigma_db"]
    rng = np.random.default_rng(seed)
    ec = ebn0_coded_db + rng.normal(0.0, sigma_ebn0_db, n_boot)
    eu = EBN0_UNCODED_DB + rng.normal(0.0, sigma_uncoded_db, n_boot)
    ed = e_dec_j * (1.0 + rng.normal(0.0, e_dec_rel, n_boot))
    out = [v for v in (_dstar_raw(a, b, c, eta, n, model)
                       for a, b, c in zip(ec, eu, ed)) if v is not None]
    out = np.array(out)
    return {"sigma_m": float(out.std(ddof=1)),
            "ci_low_m": float(np.percentile(out, 2.5)),
            "ci_high_m": float(np.percentile(out, 97.5))}


def delta_dstar_ci(req_a_db, e_dec_a_j, req_b_db, e_dec_b_j, eta, n, model,
                   sigma_a_db, sigma_b_db,
                   sigma_uncoded_db=None,
                   e_dec_rel=E_DEC_REPEAT_REL, n_boot=20000, seed=_CI_SEED):
    """Δd* = d*(b)/d*(a) − 1 的區間（百分比）。

    未編碼的 Eb/N0 對兩個組態用**同一個**抽樣值（共模，見上方說明）；
    E_dec 的重複性則對兩者獨立抽（那是兩次分別的 gate-level run）。
    """
    if sigma_uncoded_db is None:
        sigma_uncoded_db = uncoded_ebn0_ci()["sigma_db"]
    rng = np.random.default_rng(seed)
    ea = req_a_db + rng.normal(0.0, sigma_a_db, n_boot)
    eb = req_b_db + rng.normal(0.0, sigma_b_db, n_boot)
    eu = EBN0_UNCODED_DB + rng.normal(0.0, sigma_uncoded_db, n_boot)   # 共模
    da = e_dec_a_j * (1.0 + rng.normal(0.0, e_dec_rel, n_boot))
    db = e_dec_b_j * (1.0 + rng.normal(0.0, e_dec_rel, n_boot))
    out = []
    for xa, xb, u, ya, yb in zip(ea, eb, eu, da, db):
        d_a = _dstar_raw(xa, u, ya, eta, n, model)
        d_b = _dstar_raw(xb, u, yb, eta, n, model)
        if d_a and d_b:
            out.append(100.0 * (d_b / d_a - 1.0))
    out = np.array(out)
    return {"sigma_pct": float(out.std(ddof=1)),
            "ci_low_pct": float(np.percentile(out, 2.5)),
            "ci_high_pct": float(np.percentile(out, 97.5))}


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
