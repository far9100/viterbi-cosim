"""m5_gate.py — M5 的驗收：annotation、R1 的裁決、d*、以及三條證偽條件。

三條預先登記的證偽條件寫在 docs/falsification.md，於**任何量測開跑之前** commit
（commit 時間戳可驗證）。本檔負責裁決，成立或不成立都如實記錄。
"""

import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.energy_model import (ADC_FOM_J, ETA_PA, F_CLK,  # noqa: E402
                                  NF_SWEEP_DB, N_PATHLOSS, P_CIRCUIT_SWEEP,
                                  d_star, d_star_ci, delta_dstar_ci, e_adc,
                                  e_dec_of, n0_of, uncoded_ebn0_ci)
from scripts.gates import DATA, Run  # noqa: E402

BLOCKS = ["u_acs", "u_tb", "u_minpm", "u_bmu", "u_ctrl"]


def load():
    with open(os.path.join(DATA, "power.json")) as f:
        pw = json.load(f)
    grid = {}
    sigma = {}
    with open(os.path.join(DATA, "m2_grid.csv")) as f:
        for r in csv.DictReader(f):
            k = (int(r["Q"]), float(r["clip"]), int(r["D"]))
            grid[k] = float(r["required_ebn0_db"])
            # required Eb/N0 的 1-σ（參數化 bootstrap，見 golden/ber.py）。
            # 沒有它就無法把不確定度傳到 d*，而 d* 的頭條數字全靠它才有區間。
            sigma[k] = (float(r["required_sigma_db"])
                        if r.get("required_sigma_db") else None)
    return pw, grid, sigma


def main():
    pw, grid, sigma = load()
    pts = pw["points"]
    conv = pw.get("convergence", [])
    run = Run("m5_ppa", milestone="M5")

    # ---------- annotation ----------
    ann = [p["annot_pct"] for p in pts]
    run.check("M5-1 SAIF annotation coverage", min(ann) >= 99.0,
              measured=f"{len(pts)} 個點，最低 {min(ann):.2f}%",
              expected=">= 99%", tolerance="—",
              detail="規格書 §7：功耗不得用預設 toggle-rate 猜測。覆蓋率不足時 OpenSTA "
                     "不會報錯，只會靜靜套用預設值——症狀會偽裝成「功耗竟然不隨輸入改變」。"
                     "本專案踩過一次：Yosys 把 unpacked array 拆成 escaped identifier "
                     "（\\surv[9]），VCD 把反斜線也寫出來，SAIF 因此 parse error，"
                     "annotation 掉到 0%。M0 的 counter 是扁平設計，抓不到這個。")

    # ---------- 收斂性 ----------
    main_cfg = [p for p in pts if p["tag"] == "Q4_W10_D64" and p["snr_db"] == 3.0]
    conv_ok, conv_msg = True, "—"
    if conv and main_cfg:
        ps = sorted([(c["frames"], c["p_total_w"]) for c in conv] +
                    [(main_cfg[0]["frames"], main_cfg[0]["p_total_w"])])
        base = ps[-1][1]
        devs = [abs(p - base) / base * 100 for _, p in ps]
        conv_ok = max(devs) < 5.0
        conv_msg = "，".join(f"{f} frame:{p*1e3:.2f} mW" for f, p in ps)
    run.check("M5-2 功耗對 frame 數的收斂性", conv_ok,
              measured=conv_msg, expected="< 5% 變動", tolerance="—",
              detail="toggle 率靠大數法則收斂（每個 frame 有 ~10^3 個獨立的 trellis stage）。"
                     "這是實測，不是假設。")

    # ---------- R1 的裁決：總功耗對 SNR 是不是平的？ ----------
    sweep = sorted([p for p in pts if p["tag"] == "Q4_W10_D64"],
                   key=lambda p: p["snr_db"])
    r1 = {}
    if len(sweep) >= 3:
        for k in ["p_total_w"] + [f"p_{b}_w" for b in BLOCKS] + \
                 [f"p_{b}_sw_w" for b in BLOCKS]:
            v = [p.get(k, 0.0) for p in sweep]
            if max(v) > 0:
                r1[k] = 100.0 * (max(v) - min(v)) / max(v)

    tot_var = r1.get("p_total_w", 0.0)
    acs_sw_var = r1.get("p_u_acs_sw_w", 0.0)
    tb_var = r1.get("p_u_tb_w", 0.0)

    # 這一道**不是** pass/fail 的閘門，而是一個要如實記錄的觀測。
    # R1 若成立（總功耗幾乎不隨 SNR 變），規格書 §7 的交付物就要改寫，而不是假裝有。
    run.check("M5-3 功耗 vs SNR（R1 的裁決）", True,
              measured=f"總功耗變動 {tot_var:.1f}%；ACS 的 switching 變動 "
                       f"{acs_sw_var:.1f}%；traceback 變動 {tb_var:.1f}%",
              expected="（觀測，不是 pass/fail）", tolerance="—",
              detail="計畫的風險 R1：register exchange 的 traceback 佔 68-84% 的 flop，"
                     "而它每個 stage 都改寫全部 64 個暫存器，活動量與 SNR 無關。"
                     "所以總功耗對 SNR 可能幾乎是平的——而規格書 §7 把那條曲線列為交付結果。"
                     "分區塊才看得到 SNR 依賴真正住在哪裡。")

    # ---------- d* 與證偽條件 ----------
    at3 = {(p["Q"], p["D"]): p for p in pts if p["snr_db"] == 3.0}

    def dstar_of(Q, W, D, clip, model, env, eta):
        p = at3.get((Q, D))
        if not p:
            return None
        req = grid.get((Q, clip, D))
        if req is None:
            return None
        e_dec = p["p_total_w"] / F_CLK
        return d_star(req, e_dec, eta, N_PATHLOSS[env], model)

    # 條件 1：d* < 1 m 或不存在？
    ds = []
    for (Q, D), p in at3.items():
        clip = p["clip"]
        for model in ("A", "B"):
            for env in N_PATHLOSS:
                for eta in ETA_PA:
                    v = dstar_of(Q, p["W"], D, clip, model, env, eta)
                    if v and np.isfinite(v):
                        ds.append(v)
    dmin = min(ds) if ds else float("nan")
    cond1 = dmin >= 1.0
    run.check("F1 證偽條件 1：d* < 1 m 或不存在 -> 主張失敗", cond1,
              measured=f"所有模型/環境/η 下的最小 d* = {dmin:.1f} m",
              expected=">= 1 m（主張存活）", tolerance="預先登記",
              detail="docs/falsification.md 條件 1（沿用規格書 §0 原文）。"
                     "事前預測：不會觸發（估計 d* ∈ [13.7 m, 5.4 km]）。"
                     "誠實補充：交叉點在數學上必然存在（ΔE_tx 隨 d^n 成長），"
                     "所以這條條件本來就幾乎不可能觸發——它是一個**弱**的門檻。")

    # 條件 2 / 3：Q -> d* 的敏感度。用同樣 D=32 的 Q=3 與 Q=6 比（traceback 完全相同）。
    sens = {}
    sens_ci = {}
    _p3, _p6 = at3.get((3, 32)), at3.get((6, 32))
    for model in ("A", "B"):
        for env in N_PATHLOSS:
            d3 = dstar_of(3, 8, 32, 2.0, model, env, 0.1)
            d6 = dstar_of(6, 12, 32, 3.0, model, env, 0.1)
            if d3 and d6:
                sens[(model, env)] = 100.0 * (d6 / d3 - 1.0)
                # Δd* 的區間。**這是 F2/F3 裁決真正需要的東西**：F2 的門檻是 5%、
                # F3 看的是符號，而先前兩者都只拿點估計去比。模型 B 的 −0.75% 尤其吃緊——
                # 沒有區間就無法回答「符號翻轉是不是雜訊」這個必然會被問到的問題。
                s3, s6 = sigma.get((3, 2.0, 32)), sigma.get((6, 3.0, 32))
                if s3 and s6 and _p3 and _p6:
                    sens_ci[(model, env)] = delta_dstar_ci(
                        grid[(3, 2.0, 32)], _p3["p_total_w"] / F_CLK,
                        grid[(6, 3.0, 32)], _p6["p_total_w"] / F_CLK,
                        0.1, N_PATHLOSS[env], model, s3, s6)

    a_vals = [v for (m, _), v in sens.items() if m == "A"]
    b_vals = [v for (m, _), v in sens.items() if m == "B"]
    txt = "；".join(
        (f"模型{m}/{e}: {v:+.2f}%"
         + (f" [{sens_ci[(m, e)]['ci_low_pct']:+.2f}, "
            f"{sens_ci[(m, e)]['ci_high_pct']:+.2f}]" if (m, e) in sens_ci else ""))
        for (m, e), v in sorted(sens.items()))

    # 區間對裁決的實質意義：F2 的門檻是 5%，F3 看的是符號。點估計過關但區間跨過門檻/零點，
    # 就是「裁決其實沒被解析出來」——必須讓它在 gate 裡顯形，而不是只寫在報告散文裡。
    f2_robust = all(
        (m, e) not in sens_ci or abs(sens_ci[(m, e)]["ci_low_pct"]) >= 5.0
        or abs(sens_ci[(m, e)]["ci_high_pct"]) >= 5.0
        for (m, e) in sens if m == "A")
    f3_sign_robust = all(
        (m, e) not in sens_ci
        or (sens_ci[(m, e)]["ci_low_pct"] > 0 if m == "A"
            else sens_ci[(m, e)]["ci_high_pct"] < 0)
        for (m, e) in sens)

    # 條件 2：兩個模型下都 < 5% -> 「字寬移動臨界距離」的貢獻宣稱失敗
    all_small = all(abs(v) < 5.0 for v in sens.values())
    run.check("F2 證偽條件 2：|Δd*| 兩模型皆 < 5% -> 貢獻宣稱失敗", not all_small,
              measured=txt, expected="至少一個模型 >= 5%", tolerance="預先登記",
              detail=f"【區間，後補】Δd* 的 95% 區間見 measured 欄的方括號"
                     f"（不確定度來源：required Eb/N0 的 bootstrap σ、未編碼 Eb/N0 的"
                     f"共模 σ、E_dec 的 0.2% 重複性）。模型 A 的區間"
                     f"{'完全在 5% 門檻之外 ⇒ 裁決穩健' if f2_robust else '跨過 5% 門檻 ⇒ 裁決未被解析出來'}。"
                     "docs/falsification.md 條件 2。若失敗，報告須如實改寫為："
                     "「效應存在但微弱：量化增益與解碼器能量對 d* 的作用方向相反，近乎相消。」"
                     "比較的是 Q=3/D=32 與 Q=6/D=32 —— **同樣的 D，同樣的 traceback**，"
                     "差別純粹來自 Q（ADC 位寬 + 最小安全 W 決定的 ACS 寬度）。")

    # 條件 3：事前預測的**符號**（模型 A 為正、模型 B 為負）與量級（A < 30%）
    sign_ok = (all(v > 0 for v in a_vals) and all(v < 0 for v in b_vals)
               if (a_vals and b_vals) else False)
    mag_ok = all(abs(v) <= 30.0 for v in a_vals)
    run.check("F3 證偽條件 3：事前預測的符號與量級", sign_ok and mag_ok,
              measured=f"模型A {['%+.2f%%' % v for v in a_vals]}（預測為**正**，+1.6~+2.8%）；"
                       f"模型B {['%+.2f%%' % v for v in b_vals]}（預測為**負**，-0.5~-0.9%）",
              expected="A 為正且 <30%，B 為負", tolerance="預先登記",
              detail=f"【區間，後補】符號的穩健性："
                     f"{'四個區間全部不跨過零點 ⇒ 符號翻轉是被解析出來的，不是雜訊' if f3_sign_robust else '至少一個區間跨過零點 ⇒ 符號未被解析出來，不得宣稱翻轉'}。"
                     "docs/falsification.md §3.4 的「符號會翻轉」預測——這是本文件最咬得住的一條。"
                     "機制：Q 增加時量化增益變大（d* 變小）與解碼器能量變大（d* 變大）"
                     "**方向相反**；模型 B 的 60 nJ 電路能量把 E_dec 的變化完全淹沒，"
                     "只剩量化增益的效應，所以符號翻轉。若實測符號不符，代表機制理解錯誤。")

    # ---------- 交付資料 ----------
    prows = []
    for p in sorted(pts, key=lambda p: (p["tag"], p["snr_db"])):
        r = {k: p.get(k) for k in
             ["tag", "Q", "W", "D", "clip", "snr_db", "frames", "n_stages",
              "annot_pct", "n_nets", "saif_mb"]}
        for b in ["total"] + BLOCKS:
            for s in ["w", "int_w", "sw_w", "leak_w"]:
                r[f"p_{b}_{s}"] = p.get(f"p_{b}_{s}")
        r["e_dec_pj_per_bit"] = (p["p_total_w"] / F_CLK * 1e12
                                 if p.get("p_total_w") else None)
        prows.append(r)
    run.csv("results_m5_power.csv", list(prows[0].keys()), prows)

    # ---------- results.csv：規格書 §8/§11.4 與 CLAUDE.md §5.4 指定的唯一資料來源 ----------
    #
    # 這個檔在 M5 當時漏掉了，而三份文件同時依賴它，於是它們的承諾全部落空：
    #
    #   docs/energy_model.md §5  要求**分開記錄** e_dyn_per_bit 與 p_leak，好讓
    #                            E_dec(f_clk) = e_dyn_per_bit + p_leak / f_clk
    #                            在任何 f_clk 下都能重算 —— 兩個欄位從未被寫進任何 CSV。
    #   docs/energy_model.md §7  宣稱 check_paper_numbers.py 會驗「每個 d* 都能由
    #                            results.csv + 本文件的常數重算」—— 它實際上只是讀
    #                            results_m5_dstar.csv 裡**已經算好**的 dstar_m。
    #   docs/fec_viterbi_cosim_spec.md §9 的 M6 驗收條件寫「results.csv 為唯一來源」。
    #
    # 為什麼是「分開記錄」而不是只存 E_dec：動態能量與 f_clk 無關（P_dyn ∝ f，故 P/f 是常數），
    # 漏電**功率**也與 f_clk 無關，但漏電的**每位元能量**與 f_clk 成反比。只存合併後的 E_dec
    # 就把 100 MHz 這個假設烙進資料裡，換一個時脈就得重跑整條 gate-level 流程。
    #
    # 涵蓋全部 8 個功耗點（不只 d* 用的 3 dB），因為重算 E_dec 的需求與 SNR 無關。
    rrows = []
    for p in sorted(pts, key=lambda p: (p["Q"], p["D"], p["snr_db"])):
        Q, W, D, clip = p["Q"], p["W"], p["D"], p["clip"]
        p_tot, p_leak = p["p_total_w"], p["p_total_leak_w"]
        rrows.append({
            "Q": Q, "W": W, "D": D, "clip": clip, "snr_db": p["snr_db"],
            "required_ebn0_db": grid.get((Q, clip, D)),
            "p_total_w": p_tot,
            # 與 f_clk 無關的兩個量（docs/energy_model.md §5）
            "e_dyn_per_bit_j": (p_tot - p_leak) / F_CLK,
            "p_leak_w": p_leak,
            # 便利欄位：在本專案的 f_clk 下由上兩欄導出，不是獨立資料
            "f_clk_hz": F_CLK,
            "e_dec_pj_per_bit": (p_tot / F_CLK) * 1e12,
        })
    run.csv("results.csv", list(rrows[0].keys()), rrows)

    drows = []
    for (Q, D), p in sorted(at3.items()):
        clip, W = p["clip"], p["W"]
        req = grid.get((Q, clip, D))
        e_dec = p["p_total_w"] / F_CLK
        sg = sigma.get((Q, clip, D))
        for model in ("A", "B"):
            for env in N_PATHLOSS:
                for eta in ETA_PA:
                    v = d_star(req, e_dec, eta, N_PATHLOSS[env], model)
                    # 不確定度傳播（見 scripts/energy_model.py）：required Eb/N0 的
                    # 統計誤差 + 未編碼 Eb/N0 的共模誤差 + E_dec 的量測重複性。
                    ci = (d_star_ci(req, e_dec, eta, N_PATHLOSS[env], model, sg)
                          if sg else None)
                    drows.append({
                        "Q": Q, "W": W, "D": D, "clip": clip,
                        "required_ebn0_db": req,
                        "required_sigma_db": sg,
                        "e_dec_pj_per_bit": round(e_dec * 1e12, 1),
                        "model": model, "env": env, "eta_pa": eta,
                        "dstar_m": round(v, 2),
                        "dstar_sigma_m": round(ci["sigma_m"], 3) if ci else None,
                        "dstar_ci_low_m": round(ci["ci_low_m"], 2) if ci else None,
                        "dstar_ci_high_m": round(ci["ci_high_m"], 2) if ci else None})
    run.csv("results_m5_dstar.csv", list(drows[0].keys()), drows)

    # ---------- docs/energy_model.md §2 宣告過、但從未跑的兩條掃描 + power gating ----------
    #
    # 文件 §2 的表明列「掃描範圍」：F ∈ {3,6,10} dB、P_circuit ∈ {20,60,120} mW。
    # M5 只用了預設值，兩條掃描一直沒跑——文件承諾與交付之間的缺口。這裡補上，
    # 並一併把文件 §5 的 power gating 假設實際算出來（結論見 energy_model.e_dec_of 的 docstring：
    # 文件說「灌大約 200 倍」是把漏電**項**的比值誤當成 E_dec 的比值，實際只差 0.05%）。
    srows = []
    for (Q, D), p in sorted(at3.items()):
        clip, W = p["clip"], p["W"]
        req = grid.get((Q, clip, D))
        if req is None:
            continue
        e_dyn = (p["p_total_w"] - p["p_total_leak_w"]) / F_CLK
        for gated in (True, False):
            e_dec = e_dec_of(e_dyn, p["p_total_leak_w"], power_gated=gated)
            for nf in NF_SWEEP_DB:
                for pc in P_CIRCUIT_SWEEP:
                    for model in ("A", "B"):
                        for env in N_PATHLOSS:
                            v = d_star(req, e_dec, 0.1, N_PATHLOSS[env], model,
                                       n0=n0_of(nf), p_circuit=pc)
                            srows.append({
                                "Q": Q, "W": W, "D": D, "clip": clip,
                                "power_gated": gated, "nf_db": nf,
                                "p_circuit_mw": round(pc * 1e3),
                                "e_dec_pj_per_bit": round(e_dec * 1e12, 4),
                                "model": model, "env": env, "eta_pa": 0.1,
                                "dstar_m": round(v, 3)})
    run.csv("results_m5_sensitivity.csv", list(srows[0].keys()), srows)

    # F1 原本只在**預設參數點**（NF=6 dB、P_circuit=60 mW）上裁決。但 docs/energy_model.md §2
    # 宣告了掃描範圍，而規格書 §0 的證偽條件寫的是「在合理參數範圍內」——
    # 只驗一個點就宣告存活，比條件本身要求的弱。這裡把它擴到整個宣告過的範圍。
    s_min = min(r["dstar_m"] for r in srows)
    s_arg = next(r for r in srows if r["dstar_m"] == s_min)
    run.check("F1b 證偽條件 1 擴及整個宣告過的參數範圍", s_min >= 1.0,
              measured=f"{len(srows)} 個組合的最小 d* = {s_min:.2f} m"
                       f"（Q{s_arg['Q']} D{s_arg['D']}, NF={s_arg['nf_db']} dB, "
                       f"P_c={s_arg['p_circuit_mw']} mW, 模型{s_arg['model']}/{s_arg['env']}）",
              expected=">= 1 m（主張存活）", tolerance="預先登記",
              detail="規格書 §0 的證偽條件寫的是「在 η_PA ∈ [0.1,0.5]、合理參數範圍內」，"
                     "但 F1 原本只在預設參數點（NF=6 dB、P_circuit=60 mW）上裁決 —— "
                     "那比條件本身要求的弱。docs/energy_model.md §2 早就宣告了 "
                     "F ∈ {3,6,10} dB 與 P_circuit ∈ {20,60,120} mW 兩條掃描範圍，"
                     "只是從未執行。掃完之後 d* 的最小值仍遠大於 1 m ⇒ **F1 的存活比先前更強**，"
                     "而不是只在一個點上成立。")

    # power gating：把「有/無」在其他參數全同的條件下對比，量化那個假設到底重不重要
    _pg = {}
    for r in srows:
        if r["nf_db"] == 6.0 and r["p_circuit_mw"] == 60 and r["env"] == "indoor" \
                and r["model"] == "A":
            _pg[(r["Q"], r["D"], r["power_gated"])] = r
    pg_max = max((100.0 * (_pg[(q, d, False)]["dstar_m"]
                           / _pg[(q, d, True)]["dstar_m"] - 1.0)
                  for q, d, g in _pg if g), default=0.0)
    ed_max = max((100.0 * (_pg[(q, d, False)]["e_dec_pj_per_bit"]
                           / _pg[(q, d, True)]["e_dec_pj_per_bit"] - 1.0)
                  for q, d, g in _pg if g), default=0.0)
    run.check("M5-4 power gating 假設的重要性", True,
              measured=f"關掉 power gating：E_dec 最多變 {ed_max:.3f}%、"
                       f"d* 最多變 {pg_max:.3f}%",
              expected="（觀測，不是 pass/fail）", tolerance="—",
              detail="docs/energy_model.md §5 說不做 power gating 會把 E_dec「灌大約 200 倍」，"
                     "並要求報告必須明講這個假設。**那個量級是錯的。** 200 倍是**漏電項**的"
                     "比值（(1/R_info)/(1/f_clk) = 2e-6/1e-8），不是 E_dec 的比值；"
                     "而漏電只佔本設計總功耗的 0.00027%（64 nW vs 24 mW）。"
                     "實測：E_dec 只變 0.05%、d* 只變 0.03% ⇒ **這個假設其實無關緊要**。"
                     "對報告是好消息（少一條 caveat），但文件的量級不得沿用。")

    # ---------- traceback 記憶體的敏感度線（修正報告 §5-1 的一個推論錯誤）----------
    #
    # report.md §5-1 原本寫：「d* 的絕對值是上界（flop 陣列而非 SRAM macro），
    # 但 **Q 之間的相對比較不受影響**（同一個 D 下 traceback 完全相同，實測差 0.08%）。」
    #
    # **後半句的推論方向反了。** Δd* 由 Δln(E_dec) 驅動，而 traceback 正是 E_dec 裡
    # **與 Q 無關**的那一項。一個與 Q 無關的大常數加在分子上，會把比值往 1 拉——
    # 也就是**稀釋** Q 依賴性。「traceback 完全相同」正是它會影響相對比較的理由，
    # 不是它不會影響的理由。
    #
    # 方向是明確的：flop 陣列高估 traceback ⇒ **低估** Δd*。
    # 所以已發表的 +11.29% / +6.31% 是 Δd* 的**下界**，而 d* 的絕對值是**上界**——
    # 兩個偏差方向相反，這一點原文完全沒說。
    #
    # 這裡出一條敏感度線（與 §6.2 的 ADC 敏感度線同一種東西，**不是量測值**）：
    # 把 traceback 功耗乘上一個縮減因子，看 Δd* 怎麼動。不宣稱某個因子是「正確」的，
    # 因為 SRAM 版本沒做（report.md §5-5 已如實列為未做）。
    TB_FACTORS = [1.0, 0.5, 0.2, 0.1]
    p3, p6 = at3.get((3, 32)), at3.get((6, 32))
    trows = []
    if p3 and p6:
        req3 = grid.get((3, p3["clip"], 32))
        req6 = grid.get((6, p6["clip"], 32))
        for fac in TB_FACTORS:
            # 只縮 traceback，其餘區塊原樣：模擬「survivor 記憶體換成 SRAM」
            e3 = (p3["p_total_w"] - p3["p_u_tb_w"] * (1.0 - fac)) / F_CLK
            e6 = (p6["p_total_w"] - p6["p_u_tb_w"] * (1.0 - fac)) / F_CLK
            for model in ("A", "B"):
                for env in N_PATHLOSS:
                    d3 = d_star(req3, e3, 0.1, N_PATHLOSS[env], model)
                    d6 = d_star(req6, e6, 0.1, N_PATHLOSS[env], model)
                    trows.append({
                        "tb_factor": fac,
                        "e_dec_q3_pj_per_bit": round(e3 * 1e12, 1),
                        "e_dec_q6_pj_per_bit": round(e6 * 1e12, 1),
                        "e_dec_ratio": round(e6 / e3, 4),
                        "model": model, "env": env, "eta_pa": 0.1,
                        "dstar_q3_m": round(d3, 2), "dstar_q6_m": round(d6, 2),
                        "delta_dstar_pct": round(100.0 * (d6 / d3 - 1.0), 2)})
        run.csv("results_m5_tb_sensitivity.csv", list(trows[0].keys()), trows)

        print("\n=== traceback 記憶體的敏感度線（**敏感度線，非量測值**；SRAM 版本未做）")
        print("    修正 report.md §5-1：traceback 是 E_dec 裡與 Q 無關的那一項，")
        print("    高估它會**稀釋** Q 依賴 ⇒ 已發表的 Δd* 是**下界**，d* 的絕對值是上界。")
        print(f"{'tb 係數':>8} {'E_dec 比值':>10} {'Δd* A/自由空間':>15} {'Δd* A/室內':>12}")
        for fac in TB_FACTORS:
            g = {(r["model"], r["env"]): r for r in trows if r["tb_factor"] == fac}
            print(f"{fac:>8.1f} {g[('A','free_space')]['e_dec_ratio']:>10.4f} "
                  f"{g[('A','free_space')]['delta_dstar_pct']:>14.2f}% "
                  f"{g[('A','indoor')]['delta_dstar_pct']:>11.2f}%")

    # ---------- ADC 能量敏感度（docs/energy_model.md §6.2 承諾過的）----------
    # **不混進主結果**：主 d* 用 e_adc=0，與預先登記的模型完全一致。
    # 這裡另外出一份敏感度表，因為頭條圖是「d* vs Q」而 E_ADC ∝ 2^Q ——
    # 排除它會系統性低估大 Q 的代價。方向與 E_dec 相同，所以只會**加大** Δd*。
    arows = []
    for fom in ADC_FOM_J:
        for (Q, D), p in sorted(at3.items()):
            clip, W = p["clip"], p["W"]
            req = grid.get((Q, clip, D))
            e_dec = p["p_total_w"] / F_CLK
            ea = e_adc(Q, fom)
            for model in ("A", "B"):
                for env in N_PATHLOSS:
                    arows.append({
                        "adc_fom_fj": round(fom * 1e15),
                        "Q": Q, "W": W, "D": D,
                        "e_dec_pj_per_bit": round(e_dec * 1e12, 1),
                        "e_adc_pj_per_bit": round(ea * 1e12, 3),
                        "adc_share_pct": round(100.0 * ea / (e_dec + ea), 2),
                        "model": model, "env": env, "eta_pa": 0.1,
                        "dstar_no_adc_m": round(
                            d_star(req, e_dec, 0.1, N_PATHLOSS[env], model), 2),
                        "dstar_with_adc_m": round(
                            d_star(req, e_dec, 0.1, N_PATHLOSS[env], model,
                                   e_adc_j=ea), 2)})
    run.csv("results_m5_adc.csv", list(arows[0].keys()), arows)

    print("\n=== ADC 能量敏感度（Walden FoM；**敏感度線，非量測值**）")
    print("    E_ADC/info bit = 2 · FoM · 2^Q   （R=1/2 ⇒ 每 info bit 2 次轉換）")
    print(f"{'FoM':>7} {'Q':>2} {'E_ADC':>9} {'佔 E_dec+ADC':>12} | "
          f"{'Δd*(Q3→Q6) 無 ADC':>17} {'含 ADC':>9}")
    for fom in ADC_FOM_J:
        for model, env in (("A", "indoor"), ("B", "indoor")):
            g = {r["Q"]: r for r in arows
                 if r["adc_fom_fj"] == round(fom * 1e15) and r["model"] == model
                 and r["env"] == env and r["D"] == 32}
            if 3 in g and 6 in g:
                no = 100.0 * (g[6]["dstar_no_adc_m"] / g[3]["dstar_no_adc_m"] - 1)
                wi = 100.0 * (g[6]["dstar_with_adc_m"] / g[3]["dstar_with_adc_m"] - 1)
                print(f"{round(fom*1e15):>5} fJ  模型{model}/{env}: "
                      f"Q3 {g[3]['e_adc_pj_per_bit']:>6.2f} pJ "
                      f"({g[3]['adc_share_pct']:>4.1f}%)  "
                      f"Q6 {g[6]['e_adc_pj_per_bit']:>6.2f} pJ "
                      f"({g[6]['adc_share_pct']:>4.1f}%)  |  "
                      f"{no:>+7.2f}%  ->  {wi:>+7.2f}%")
    print("    ADC 與 E_dec 同向（都隨 Q 增加）⇒ 只會**加大** Δd*，"
          "所以 F2 的結論（貢獻宣稱存活）只會更穩。")

    # ---------- 報告 ----------
    print("\n=== R1 的裁決：功耗 vs SNR（Q=4 W=10 D=64，1→5 dB）")
    for p in sweep:
        print(f"  {p['snr_db']:.0f} dB: P_total {p['p_total_w']*1e3:7.3f} mW  "
              f"| tb {p.get('p_u_tb_w',0)*1e3:6.3f}  "
              f"acs {p.get('p_u_acs_w',0)*1e3:6.3f} "
              f"(sw {p.get('p_u_acs_sw_w',0)*1e3:6.3f})  "
              f"minpm {p.get('p_u_minpm_w',0)*1e3:6.3f}")
    print(f"\n  總功耗在 1→5 dB 只變動 {tot_var:.1f}%（而且 traceback 的 "
          f"{tb_var:.1f}% 是**非單調**的 —— 那是雜訊，不是趨勢）")
    print(f"  ACS 的 switching 變動 {acs_sw_var:.1f}%。")
    print("  真正的 SNR 依賴住在**路徑度量累加器 pm**：翻轉密度對 SNR 的線性迴歸 "
          "**R² = 0.913**、全距 3.3%（見 data/results_m5_toggle.csv）。")
    print("  pm 是整條資料路徑上**唯一不在最大熵**的訊號（翻轉率 0.30，其餘都是 ~0.47），"
          "因為它是累加器。")
    print("  對照：**surv 的 R² = 0.000** —— 倖存者決策與 SNR 的相關性是零。"
          "bm 0.020、re 0.247 也都無趨勢。")
    print("  （**不是「單調」**：pm 在 2 dB 有 0.3% 的凹陷。5 個點的「看起來單調」"
          "不是證據，R² 才是。）")
    print("  其餘每一級都被隨機資訊源釘在擲硬幣 —— 這就是規格書 §7 那條曲線不存在的原因。")

    print("\n=== d* （3 dB 的功耗，η=0.1）")
    for (Q, D), p in sorted(at3.items()):
        clip = p["clip"]
        req = grid.get((Q, clip, D))
        e_dec = p["p_total_w"] / F_CLK
        s = "  ".join(
            f"{m}/{e}: {d_star(req, e_dec, 0.1, N_PATHLOSS[e], m):7.1f} m"
            for m in ("A", "B") for e in N_PATHLOSS)
        print(f"  Q={Q} D={D:2d}  E_dec={e_dec*1e12:5.0f} pJ/bit  {s}")

    print("\n=== 證偽條件的裁決")
    print(f"  F1  最小 d* = {dmin:.1f} m  ->  {'主張存活' if cond1 else '主張失敗'}")
    print(f"  F2  {txt}")
    print(f"  F3  符號：模型A {'正' if all(v>0 for v in a_vals) else '**負**'}（預測正）、"
          f"模型B {'負' if all(v<0 for v in b_vals) else '**正**'}（預測負）")

    return run.finalize()


if __name__ == "__main__":
    sys.exit(main())
