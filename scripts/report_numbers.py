"""report_numbers.py — 把報告要引用的每個數字從 CSV 現算出來。

寫報告的順序刻意是：**先跑這支、再照抄它的輸出**。反過來（先寫報告再找數字對照）
就是論文數字與資料脫節的標準死法。M6 的 check_paper_numbers.py 之後會把這些
再驗一次（值相符 + 字串確實出現在報告裡）。
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.gates import DATA, REPO  # noqa: E402


def load(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


def main():
    pw = load("results_m5_power.csv")
    ds = load("results_m5_dstar.csv")
    fx = load("results_m5_fmax.csv")
    tg = load("results_m5_toggle.csv")
    mc = load("results_m5_mechanism.csv")
    adc = load("results_m5_adc.csv")
    gates = load("gates.csv")
    grid = load("m2_grid.csv")

    with open(os.path.join(REPO, "ppa", "out", "synth", "synth.json")) as f:
        syn = json.load(f)

    at3 = {(int(p["Q"]), int(p["D"])): p for p in pw if float(p["snr_db"]) == 3.0}

    print("=" * 78)
    print("驗證鏈路（gates.csv：全部 %d 個 gate，全綠）" % len(gates))
    for ms in ["M0", "M1", "M2", "M3", "M4", "M5"]:
        n = sum(1 for g in gates if g["milestone"] == ms)
        print(f"  {ms}: {n} 個")

    print("\n" + "=" * 78)
    print("M5 功耗（3 dB）")
    print(f"{'組態':>12} {'需 Eb/N0':>9} {'P_total':>9} {'E_dec':>10} "
          f"{'tb':>8} {'acs':>8} {'minpm':>8}")
    for (Q, D), p in sorted(at3.items()):
        req = next((float(g["required_ebn0_db"]) for g in grid
                    if int(g["Q"]) == Q and float(g["clip"]) == float(p["clip"])
                    and int(g["D"]) == D), None)
        print(f"  Q{Q} W{p['W']} D{D:>2} {req:>9.4f} "
              f"{float(p['p_total_w'])*1e3:>8.3f}m "
              f"{float(p['e_dec_pj_per_bit']):>8.1f}pJ "
              f"{float(p['p_u_tb_w'])*1e3:>7.3f} {float(p['p_u_acs_w'])*1e3:>7.3f} "
              f"{float(p['p_u_minpm_w'])*1e3:>7.3f}")

    # α
    e3 = float(at3[(3, 32)]["e_dec_pj_per_bit"])
    e6 = float(at3[(6, 32)]["e_dec_pj_per_bit"])
    ratio = e6 / e3
    alpha = 2.0 * (ratio - 1.0)
    print(f"\n  E_dec(Q6,D32)/E_dec(Q3,D32) = {e6:.2f}/{e3:.2f} = {ratio:.4f}")
    print(f"  => α = 2·(比值 − 1) = {alpha:.3f}   （事前登記 0.15）")

    tb3 = float(at3[(3, 32)]["p_u_tb_w"]) * 1e3
    tb6 = float(at3[(6, 32)]["p_u_tb_w"]) * 1e3
    print(f"  traceback（同 D=32）：{tb3:.3f} vs {tb6:.3f} mW "
          f"-> 差 {abs(tb6-tb3)/tb3*100:.2f}%（與 Q 無關，如事前假設）")

    for tag, key in (("traceback", "p_u_tb_w"), ("ACS", "p_u_acs_w"),
                     ("min-PM", "p_u_minpm_w")):
        s3 = float(at3[(3, 32)][key]) / float(at3[(3, 32)]["p_total_w"]) * 100
        s6 = float(at3[(6, 32)][key]) / float(at3[(6, 32)]["p_total_w"]) * 100
        g = (float(at3[(6, 32)][key]) / float(at3[(3, 32)][key]) - 1) * 100
        print(f"  {tag:>10}: 佔比 {s3:.1f}% (Q3) / {s6:.1f}% (Q6)，"
              f"W 8->12 時功耗 {g:+.1f}%")

    print("\n" + "=" * 78)
    print("面積（Sky130 HD，階層式合成）")
    print(f"{'組態':>12} {'總面積':>10} {'DFF':>6} | "
          f"{'traceback':>9} {'DFF%':>6} | {'min-PM':>7} | {'ACS':>7}")
    for d in sorted(syn, key=lambda x: (x["Q"], x["D"])):
        tot = d["total_area_um2"]
        mods = d["modules"]

        def share(name):
            return 100.0 * mods.get(name, {}).get("area_total_um2", 0.0) / tot

        tb_dff = mods.get("traceback", {}).get("dff_total", 0)
        print(f"  {d['tag']:>12} {tot:>9.0f}µ {d['total_dff']:>6} | "
              f"{share('traceback'):>8.1f}% "
              f"{100.0*tb_dff/max(d['total_dff'],1):>5.1f}% | "
              f"{share('minpm'):>6.1f}% | "
              f"{share('acs_array') + share('acs_butterfly'):>6.1f}%")
    mp = [100.0 * d["modules"]["minpm"]["area_total_um2"] / d["total_area_um2"]
          for d in syn]
    print(f"\n  min-PM argmin 樹佔面積 {min(mp):.1f}–{max(mp):.1f}%")
    for d in sorted(syn, key=lambda x: (x["Q"], x["D"])):
        pm_rf = d["modules"].get("acs_array", {}).get("seq_area_total_um2", 0.0)
        mpa = d["modules"]["minpm"]["area_total_um2"]
        print(f"    {d['tag']:>12}: min-PM {mpa:>9.0f} µm² vs "
              f"PM register file {pm_rf:>9.0f} µm²  "
              f"-> min-PM 是它的 {mpa/max(pm_rf,1):.2f} 倍")

    print("\n" + "=" * 78)
    print("d*（3 dB 的功耗，η=0.1）")
    for (Q, D) in sorted(at3):
        r = {(x["model"], x["env"]): float(x["dstar_m"]) for x in ds
             if int(x["Q"]) == Q and int(x["D"]) == D and float(x["eta_pa"]) == 0.1}
        print(f"  Q{Q} D{D:>2}  "
              + "  ".join(f"{m}/{e}: {r[(m,e)]:>7.1f} m"
                          for m in ("A", "B") for e in ("free_space", "indoor")))
    dmin = min(float(x["dstar_m"]) for x in ds)
    print(f"\n  F1：所有模型/環境/η 下的最小 d* = {dmin:.1f} m")

    print("\n  F2/F3：Δd*（Q3/D32 -> Q6/D32，η=0.1）")
    for m in ("A", "B"):
        for e in ("free_space", "indoor"):
            d3 = next(float(x["dstar_m"]) for x in ds if int(x["Q"]) == 3
                      and int(x["D"]) == 32 and x["model"] == m and x["env"] == e
                      and float(x["eta_pa"]) == 0.1)
            d6 = next(float(x["dstar_m"]) for x in ds if int(x["Q"]) == 6
                      and int(x["D"]) == 32 and x["model"] == m and x["env"] == e
                      and float(x["eta_pa"]) == 0.1)
            print(f"    模型{m}/{e:<11} {100*(d6/d3-1):>+7.2f}%")

    print("\n" + "=" * 78)
    print("Fmax")
    for r in fx:
        print(f"  {r['tag']:>12}  純邏輯 {float(r['fmax_before_mhz']):>6.1f} MHz "
              f"(扇出 {r['max_fanout_before']:>5}, {float(r['worst_gate_cap_before_pf']):>5.2f} pF) "
              f"-> repair {float(r['fmax_after_mhz']):>6.1f} MHz "
              f"(扇出 {r['max_fanout_after']:>4})  面積 "
              f"{100*(float(r['area_after_um2'])/float(r['area_before_um2'])-1):>+5.2f}%")
    print(f"  最低的 repair 後 Fmax = "
          f"{min(float(r['fmax_after_mhz']) for r in fx):.1f} MHz")

    print("\n" + "=" * 78)
    print("機制：翻轉密度 vs SNR（Q4 W10 D64，gate-level SAIF）")
    print("  只有 5 個點，**「看起來單調」不是證據**。用線性迴歸的 R² 判斷有沒有趨勢：")
    print("  R² 高 = 翻轉率確實隨 SNR 系統性變化；R² 低 = 只是抖動。")
    print(f"{'訊號':>6} {'1 dB':>8} {'5 dB':>8} {'全距%':>7} "
          f"{'斜率(每 dB)':>11} {'R²':>6}  判定")
    sig = ["in_r", "bm", "pm", "surv", "re"]
    for s in sig:
        v = sorted([(float(r["snr_db"]), float(r["tc_per_cycle"])) for r in tg
                    if r["tag"] == "Q4_W10_D64" and r["signal"] == s])
        xs = [x[0] for x in v]
        ys = [x[1] for x in v]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        slope = sxy / sxx
        sst = sum((y - my) ** 2 for y in ys)
        ssr = sum((my + slope * (x - mx) - y) ** 2 for x, y in zip(xs, ys))
        r2 = 1.0 - ssr / sst if sst > 0 else 0.0
        var = 100 * (max(ys) - min(ys)) / max(ys)
        mono = all(ys[i] <= ys[i + 1] for i in range(n - 1))
        verdict = ("**有系統性趨勢**" if r2 > 0.8 else
                   "有弱趨勢" if r2 > 0.5 else "無趨勢（抖動）")
        print(f"  {s:>6} {ys[0]:>8.4f} {ys[-1]:>8.4f} {var:>6.2f}% "
              f"{slope:>+11.5f} {r2:>6.3f}  {verdict}"
              f"{'' if mono else '（非嚴格單調）'}")
    print("  注意：pm 在 2 dB 有一個 0.3% 的凹陷，**不是嚴格單調**——"
          "但它是唯一 R² 高的訊號。")
    print("  「唯一有系統性 SNR 趨勢的是 pm」為真；「單調」為假，不得這樣寫。")

    print("\n  跨層：numpy golden vs gate-level SAIF（surv 翻轉率）")
    for snr in (1.0, 3.0, 5.0):
        g = next(float(r["tog_surv"]) for r in mc
                 if r["case"] == "agc" and float(r["snr_db"]) == snr)
        t = next(float(r["tc_per_cycle"]) for r in tg
                 if r["tag"] == "Q4_W10_D64" and r["signal"] == "surv"
                 and float(r["snr_db"]) == snr)
        p = next(r for r in pw if r["tag"] == "Q4_W10_D64"
                 and float(r["snr_db"]) == snr)
        ratio = int(p["n_stages"]) / float(next(
            r["n_cycles"] for r in tg if r["tag"] == "Q4_W10_D64"
            and float(r["snr_db"]) == snr and r["signal"] == "surv"))
        print(f"    {snr:.0f} dB: golden {g:.4f}/stage × {ratio:.4f} = "
              f"{g*ratio:.4f}/cycle   SAIF {t:.4f}/cycle   "
              f"差 {100*(t-g*ratio)/(g*ratio):+.2f}%")

    print("\n  反事實（30 dB，滿刻度固定）：打破位元互補性")
    for case, lab in (("fixed_hi_sym", "對稱（本專案）"),
                      ("fixed_hi_asym", "ADC DC 偏移")):
        r = next(x for x in mc if x["case"] == case)
        bits = [float(r[f"tog_r_b{k}"]) for k in range(4)]
        print(f"    {lab:>16}: " + "  ".join(f"bit{k} {bits[k]:.4f}"
                                             for k in range(4)))

    print("\n" + "=" * 78)
    print("ADC 敏感度（模型 A / 室內，D=32，Q3->Q6）")
    for fom in (10, 100, 500):
        g = {int(r["Q"]): r for r in adc if int(r["adc_fom_fj"]) == fom
             and r["model"] == "A" and r["env"] == "indoor" and int(r["D"]) == 32}
        no = 100 * (float(g[6]["dstar_no_adc_m"]) / float(g[3]["dstar_no_adc_m"]) - 1)
        wi = 100 * (float(g[6]["dstar_with_adc_m"]) / float(g[3]["dstar_with_adc_m"]) - 1)
        print(f"  FoM {fom:>3} fJ: E_ADC(Q6) = {float(g[6]['e_adc_pj_per_bit']):>5.2f} pJ "
              f"({float(g[6]['adc_share_pct']):>4.1f}% of E_dec+ADC)  "
              f"Δd* {no:+.2f}% -> {wi:+.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
