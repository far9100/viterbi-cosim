"""m9_gate.py — M9 的裁決：最佳化過的設計上，null 還在不在？

判準來自 `docs/lowpower_baseline.md` §3（**量測前寫死**）。本檔只負責套用，不負責改判準。

## 一個必須講清楚的分寸

凍結文件的判準是用「總功耗全距 + R²」寫的。實測之後發現 **R² 在 n=5 下不可靠**：
控制組 B0′ 的 R² = 0.551、已發表的 B0 = 0.478 —— **同一個設計、同一組激勵，
R² 就跨過了 0.5 這個門檻**。所以本檔多算一個統計上正確的檢定（斜率的 t 值，
用獨立 seed 建立的 σ_null）。

**但那是事後追加的，如實標示。** 凍結判準原樣套用、原樣記錄；
t 檢定另列為補充。這與 G4b 的處理方式一致（`docs/fec_viterbi_cosim_spec.md` §6：
「G2 的同一個問題我在開跑前就抓到並修正了；G4 沒做同一件事，所以是量測之後才發現」）。
**不用事後想到的檢定去替換事前寫死的判準**，否則預先登記就失去意義。
"""

import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.m9_sweep as M9  # noqa: E402
from scripts.gates import DATA, REPO, Run  # noqa: E402

SXX = 10.0        # Σ(x−x̄)² for SNR = 1,2,3,4,5 dB

SYNTH = os.path.join(REPO, "ppa", "out", "synth")


def _area(tag):
    """從 Yosys 的 stat 檔取 top module 的總面積（µm²）。找不到回 None。

    只取 `Chip area for top module` 那一行——`Chip area for module X` 是該模組
    **自己的 cell**、不含子模組，拿它當總面積會少算一個數量級（見 ppa/synth.py 的註解）。
    """
    p = os.path.join(SYNTH, f"stat_{tag}.txt")
    if not os.path.exists(p):
        return None
    m = re.search(r"Chip area for top module '\\viterbi_top':\s*([\d.]+)",
                  open(p, encoding="utf-8", errors="replace").read())
    return float(m.group(1)) if m else None

# docs/lowpower_baseline.md §2 的事前預測（量測前 commit，不得修改）
PREREG = {
    "P1": "clock gating 的總功耗降幅 < 10%",
    "P2": "null 存活（總功耗對 SNR 的變動仍 < 2%）",
    "P3": "面積上升（多了 ICG cell），Fmax 上升，stage_en 扇出下降",
}


def fit(pts):
    """(功耗序列, 全距%, 斜率 mW/dB, R²)。"""
    pts = sorted(pts, key=lambda r: r["snr_db"])
    xs = [r["snr_db"] for r in pts]
    ys = [r["p_total_w"] * 1e3 for r in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    sst = sum((y - my) ** 2 for y in ys)
    ssr = sum((my + slope * (x - mx) - y) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ssr / sst if sst else 0.0
    return ys, 100.0 * (max(ys) - min(ys)) / max(ys), slope, r2


def verdict(range_pct, r2):
    """docs/lowpower_baseline.md §3 的三列判準，原樣套用。"""
    if range_pct < 2.0 and r2 < 0.5:
        return "null 存活"
    if range_pct >= 2.0 and r2 >= 0.5:
        return "null 消失"
    return "未解析"


def main():
    with open(os.path.join(DATA, "power_m9.json")) as f:
        m9 = json.load(f)["points"]
    with open(os.path.join(DATA, "power_m9_null.json")) as f:
        nul = json.load(f)
    with open(os.path.join(DATA, "power.json")) as f:
        b0 = json.load(f)["points"]

    run = Run("m9_lowpower", milestone="M9")

    sweeps = {
        "B0": [r for r in b0 if r["tag"] == "Q4_W10_D64"],
        "B0p": [r for r in m9 if r.get("variant") == "_rtlv" and r["Q"] == 4],
        "B1p": [r for r in m9 if r.get("variant") == "_cg_rtlv" and r["Q"] == 4],
    }
    fits = {k: fit(v) for k, v in sweeps.items()}

    # ---------- 真正的 pass/fail：量測本身有沒有壞 ----------
    #
    # 「事前預測被推翻」**不是** gate 失敗 —— 那是合法的科學結果。
    # gates.py 的 finalize() 一旦有 check 失敗就一個檔案都不寫（「半綠的資料比沒有資料
    # 更危險」），把預測裁決寫成 pass/fail 會讓一個正確的量測因為預測錯而丟掉全部產物。
    # 所以 pass/fail 只留給**代表壞掉**的東西：annotation 覆蓋率與 C2。
    ann = [r["annot_pct"] for r in m9]
    run.check("M9-1 SAIF annotation coverage", min(ann) >= 99.0,
              measured=f"{len(ann)} 個點，最低 {min(ann):.2f}%",
              expected=">= 99%", tolerance="硬性",
              detail="規格書 §7：功耗不得用預設 toggle-rate 猜測。"
                     "docs/lowpower_baseline.md §4.2 明訂這道 gate 不因 M9 而放寬。")

    # run_saif 內部對每個點做 gate-level C2，失敗會直接 raise。
    # 能走到這裡代表 16 個點的 C2 全過 —— 而 clock gating 第一版**正是死在這裡**
    # （ICG 關掉時脈 ⇒ 同步 reset 進不去 ⇒ 卡在 X），見 CHANGELOG 2026-07-29-17。
    run.check("M9-2 clock-gated netlist 的 C2", len(m9) >= 16,
              measured=f"{len(m9)} 個點全部通過 gate-level C2（run_saif 內建，失敗即 raise）",
              expected="全部通過", tolerance="零容忍",
              detail="docs/lowpower_baseline.md §4.1 的硬性順序：先過 C2 才准量功耗。"
                     "第一版 clock gating **正是死在這道**：Yosys 從 CE 推導 enable，"
                     "而同步 reset 不在 CE 裡 ⇒ ICG 關掉時脈時 reset 永遠進不去 ⇒ 卡在 X。"
                     "症狀極隱蔽（TB 只在 out_valid 為 1 時查 X，而 out_valid 自己是 X，"
                     "回報的是「0 個輸出」不是「X 錯誤」）——"
                     "**一個功能壞掉的 netlist 照樣會產生 SAIF 與漂亮的功耗數字。**")

    # ---------- clock gating 的效果（B0′ → B1′，RTL 形式已被控制）----------
    p0 = [r for r in sweeps["B0p"] if r["snr_db"] == 3.0][0]
    p1 = [r for r in sweeps["B1p"] if r["snr_db"] == 3.0][0]
    d_tot = 100.0 * (p1["p_total_w"] / p0["p_total_w"] - 1.0)

    run.check("M9-3 事前預測 P1 的裁決（觀測）", True,
              measured=f"**推翻** —— 事前登記「< 10%」，實測 {d_tot:+.1f}%"
                       f"（{p0['p_total_w'] * 1e3:.3f} -> {p1['p_total_w'] * 1e3:.3f} mW @3dB）",
              expected="（觀測，不是 pass/fail）", tolerance="預先登記",
              detail="**P1 被推翻，如實記錄。** 事前推理是「stage_en 的 duty cycle 有 94.1%，"
                     "沒什麼可關」——**推理錯在機制**：省下的不是閒置週期的時脈，而是"
                     "**每個 flop 的回授 mux**（cell 數降 36.5%）。分區塊：traceback -58.5%、"
                     "ACS -14.5%、min-PM +0.1%（純組合邏輯，沒有 flop 可 gate）。"
                     "預測錯了但量測沒錯，所以這是觀測而不是 gate 失敗。")

    # ---------- 凍結判準（原樣套用）----------
    ys1, rng1, slope1, r21 = fits["B1p"]
    v1 = verdict(rng1, r21)
    ys0, rng0, slope0, r20 = fits["B0p"]
    v0 = verdict(rng0, r20)

    run.check("M9-4 凍結判準：B1′ 的 null 裁決（觀測）", True,
              measured=f"全距 {rng1:.2f}%、R² {r21:.3f} -> **{v1}**",
              expected="（觀測，不是 pass/fail）", tolerance="預先登記（§3 三列判準）",
              detail=f"docs/lowpower_baseline.md §3 原樣套用：全距 < 2% **且** R² < 0.5 才算存活。"
                     f"B1′ 全距 {rng1:.2f}%（過關）但 R² {r21:.3f} ≥ 0.5（不過關）"
                     f"⇒ 落在第三列「未解析，不得宣稱任一方向」。"
                     f"**P2 未被證實，也未被推翻。** 對照組 B0′ 同樣是「{v0}」"
                     f"（全距 {rng0:.2f}%、R² {r20:.3f}）—— 連沒有 clock gating 的設計都判不出來，"
                     f"這本身就說明 R² 在 n=5 下解析不了（見 M9-6）。")

    # ---------- null 分布與斜率檢定（**事後追加**，如實標示）----------
    lines = []
    for key, var in (("B0p", "_rtlv"), ("B1p", "_cg_rtlv")):
        nd = nul[var]
        sd = nd["sd"]
        _, _, slope, _ = fits[key]
        s_slope = sd / math.sqrt(SXX)
        t = slope / s_slope if s_slope else float("inf")
        lines.append((key, sd, nd["range_pct"], slope, s_slope, t))

    worst_t = max(abs(x[5]) for x in lines)
    txt = "；".join(f"{k}: σ_null={sd:.4f} mW、斜率={sl:+.4f}、t={t:+.2f}"
                   for k, sd, _rp, sl, _ss, t in lines)
    run.check("M9-5 斜率是否顯著（**事後追加的檢定**）", True,
              measured=txt, expected="（觀測，不是 pass/fail）", tolerance="事後",
              detail="**這個檢定不在凍結文件裡，是量測之後才追加的，如實標示。** "
                     "凍結判準（M9-4）原樣保留、原樣記錄，不用事後想到的檢定去替換它 —— "
                     "否則預先登記就失去意義（比照 spec §6 對 G4b 的處理）。"
                     "檢定內容：跨 SNR 的 5 個點各自也帶一份 seed 雜訊，所以要檢定**斜率**而非全距。"
                     f"σ_slope = σ_null / sqrt(Sxx)，Sxx = {SXX:.0f}。|t| < 2 ⇒ 斜率與零無法區分。"
                     f"最大 |t| = {worst_t:.2f}。")

    run.check("M9-6 R² 在 n=5 下不可靠（觀測）", True,
              measured=f"同一設計、同一激勵：B0 的 R²={fit(sweeps['B0'])[3]:.3f}、"
                       f"B0′={r20:.3f} —— 跨過了 0.5 門檻",
              expected="（觀測，不是 pass/fail）", tolerance="—",
              detail="B0 與 B0′ 的差別只有 RTL 的 reset 寫法（語意等價），功耗曲線幾乎重疊，"
                     "但 R² 從 0.478 跳到 0.551。**5 個點的 R² 解析不出趨勢**，"
                     "這正是凍結判準需要 M9-5 那個 σ_null 才能誠實套用的理由 —— "
                     "而 σ_null 也正是 docs/lowpower_baseline.md §3 事前就要求的東西。")

    # ---------- 跨 SNR 的變異 == 純 seed 的變異（兩個態都成立）----------
    #
    # **自我更正。** 本檢查的第一版是「SNR 依賴是絕對量」，證據是相對全距從 0.91%
    # 漲到 1.47%。那個歸因是錯的：等 B1′ 的 null 分布也跑完之後，發現**純 seed 的
    # 相對全距用同一個倍數在漲**（0.941% -> 1.423%）。相對全距放大只說明「分母縮小了」，
    # 完全不能拿來當「SNR 依賴」的證據。
    #
    # 資料真正支持、而且比原說法更強的是這一條：
    # **在每一個態內，跨 SNR 的變異都等於純 seed 的變異**（B0′ 比值 0.97、B1′ 1.03），
    # 而這個相等關係在總功耗砍掉 42.8% 之後**依然成立**。
    # 也就是說：跨 SNR 看到的起伏**就是**資料雜訊，兩個態都沒有可解析的 SNR 效應。
    a0 = max(ys0) - min(ys0)
    a1 = max(ys1) - min(ys1)
    n0 = max(nul["_rtlv"]["p_mw"]) - min(nul["_rtlv"]["p_mw"])
    n1 = max(nul["_cg_rtlv"]["p_mw"]) - min(nul["_cg_rtlv"]["p_mw"])
    scale = (sum(ys1) / len(ys1)) / (sum(ys0) / len(ys0))
    r_b0, r_b1 = a0 / n0, a1 / n1
    run.check("M9-7 跨 SNR 的變異 == 純 seed 的變異（兩個態都成立）",
              max(abs(r_b0 - 1), abs(r_b1 - 1)) < 0.15,
              measured=f"B0′ 跨SNR {a0:.4f} vs seed {n0:.4f} mW（比值 {r_b0:.3f}）；"
                       f"B1′ 跨SNR {a1:.4f} vs seed {n1:.4f} mW（比值 {r_b1:.3f}）；"
                       f"同時總功耗 {100 * (scale - 1):+.1f}%",
              expected="兩個比值都在 1.0 ± 0.15 內", tolerance="—",
              detail="**這是 M9 最硬的一條結論，也取代了本檢查的第一版（見程式碼內的自我更正）。** "
                     "跨 SNR 掃描看到的起伏，大小與「把 SNR 固定住、只換隨機資料」看到的"
                     "完全一樣（差 3.5% 以內），而且**在總功耗砍掉 42.8% 之後仍然一樣**。"
                     "⇒ 那些起伏就是資料雜訊，兩個態都沒有可解析的 SNR 效應。"
                     "附帶的機制證據：資料相依的切換變異是一個**絕對量**，"
                     f"clock gating 幾乎動不到它（跨SNR {100 * (a1 / a0 - 1):+.1f}%、"
                     f"seed {100 * (n1 / n0 - 1):+.1f}%，對比總功耗 {100 * (scale - 1):+.1f}%）。")

    # ---------- 三態的起伏形狀完全相同 ⇒ 形狀由資料決定，不由 SNR 或設計決定 ----------
    #
    # 這是 M9 最強的一條證據，而且是圖畫出來才看見的：三條正規化後的曲線
    # **在每個 SNR 點的起伏方向與相對大小幾乎完全一致**。
    # 三個設計裡有一個功耗少 43%、RTL 寫法不同、還多了 ICG —— 它們唯一的共同點是
    # **每個 SNR 點用同一個激勵 seed**，也就是看到同一批隨機資料。
    #
    # 若那條起伏真的來自 SNR，它就該隨設計改變（不同的資料路徑對雜訊的反應不同）；
    # 若它來自「抽到哪組資料」，它就會像這樣被三個設計一起複製出來。實測是後者。
    def _norm(ys):
        m = sum(ys) / len(ys)
        return [100.0 * (y / m - 1.0) for y in ys]

    def _pearson(a, b):
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
        return num / den if den else 0.0

    nz = {k: _norm(fits[k][0]) for k in ("B0", "B0p", "B1p")}
    pairs = [("B0", "B0p"), ("B0", "B1p"), ("B0p", "B1p")]
    rs = {f"{a}~{b}": _pearson(nz[a], nz[b]) for a, b in pairs}
    run.check("M9-8 三態的起伏形狀相同（形狀由資料決定，不由 SNR）",
              min(rs.values()) > 0.95,
              measured="；".join(f"{k} r={v:+.4f}" for k, v in rs.items()),
              expected="全部 r > 0.95", tolerance="—",
              detail="三個設計（其中 B1′ 功耗少 42.8%、RTL 寫法不同、多了 6 個 ICG）"
                     "在每個 SNR 點的正規化起伏**方向與相對大小幾乎完全相同**。"
                     "它們唯一的共同點是每個 SNR 點用**同一個激勵 seed**。"
                     "若起伏來自 SNR，它應隨資料路徑改變而改變；若來自「抽到哪組資料」，"
                     "就會像這樣被三個設計一起複製。**實測是後者** ⇒ "
                     "那條「功耗 vs SNR 曲線」的形狀是激勵的指紋，不是 SNR 的函數。"
                     "這條與 M9-7（跨 SNR 變異 == 純 seed 變異）互相獨立、結論一致。")

    # ---------- 交付資料 ----------
    rows = []
    for key, label in (("B0", "B0 原RTL 無CG"), ("B0p", "B0' 改RTL 無CG"),
                       ("B1p", "B1' 改RTL 有CG")):
        ys, rng, slope, r2 = fits[key]
        var = {"B0": "", "B0p": "_rtlv", "B1p": "_cg_rtlv"}[key]
        nd = nul.get(var)
        rows.append({
            "state": key, "label": label,
            "p_1db_mw": round(ys[0], 4), "p_2db_mw": round(ys[1], 4),
            "p_3db_mw": round(ys[2], 4), "p_4db_mw": round(ys[3], 4),
            "p_5db_mw": round(ys[4], 4),
            "range_pct": round(rng, 4), "range_abs_mw": round(max(ys) - min(ys), 4),
            "slope_mw_per_db": round(slope, 5), "r2": round(r2, 4),
            "sigma_null_mw": round(nd["sd"], 5) if nd else None,
            # null 分布的全距也要落成欄位。報告 §7.3 的核心論證是
            # 「跨 SNR 的變異 == 純 seed 的變異」，那需要**兩邊的全距同時可比**；
            # 先前只有跨 SNR 的 range_abs_mw 進了 CSV，純 seed 那一邊只活在
            # power_m9_null.json 與 gate 的敘述字串裡，對不回任何欄位。
            "null_range_pct": round(nd["range_pct"], 4) if nd else None,
            "null_range_abs_mw": (round(max(nd["p_mw"]) - min(nd["p_mw"]), 4)
                                  if nd else None),
            "t_slope": (round(slope / (nd["sd"] / math.sqrt(SXX)), 3)
                        if nd else None),
            "frozen_verdict": verdict(rng, r2),
        })
    run.csv("results_m9_lowpower.csv", list(rows[0].keys()), rows)

    brows = []
    for key, var in (("B0p", "_rtlv"), ("B1p", "_cg_rtlv")):
        p = [r for r in sweeps[key] if r["snr_db"] == 3.0][0]
        for blk in ["total", "u_tb", "u_acs", "u_minpm", "u_bmu", "u_ctrl"]:
            v = p.get(f"p_{blk}_w")
            if v:
                brows.append({"state": key, "variant": var, "block": blk,
                              "p_mw": round(v * 1e3, 4),
                              "share_pct": round(100 * v / p["p_total_w"], 2)})
    run.csv("results_m9_blocks.csv", list(brows[0].keys()), brows)

    # ---- 面積的兩因子拆解 ----
    #
    # M9 的面積結論（B0→B0′ +4.04% 是 RTL 改寫的代價、B0′→B1′ −14.47% 才是純 clock gating）
    # 先前**只存在於 `rtl_lowpower/README.md` 的散文與 CHANGELOG 裡，不在任何 CSV**。
    # 那違反 CLAUDE.md §5.4「報告裡的每個數字都必須存在於 data/ 且可由 script 重生」，
    # 而它一直沒被抓到，只是因為報告當時根本沒有 M9 章節去引用它們。
    #
    # 這裡不新增 gate（面積不是 pass/fail 判準，凍結文件沒有替它訂門檻），
    # 只把已經算得出來的數字落成證據檔，讓 check_paper_numbers.py 管得到。
    arows = []
    for Q, W, D, _clip in [M9.MAIN] + M9.OTHERS:
        base = _area(f"Q{Q}_W{W}_D{D}")
        rtlv = _area(f"Q{Q}_W{W}_D{D}_rtlv")
        cg = _area(f"Q{Q}_W{W}_D{D}_cg_rtlv")
        if not (base and rtlv and cg):
            continue
        arows.append({
            "config": f"Q{Q}_W{W}_D{D}",
            "b0_um2": round(base, 1),
            "b0p_um2": round(rtlv, 1),
            "b1p_um2": round(cg, 1),
            # RTL 改寫本身的代價（混淆因子）
            "rewrite_pct": round(100 * (rtlv - base) / base, 2),
            # 對外報的降幅（相對於未改寫的 B0）
            "b1p_vs_b0_pct": round(100 * (cg - base) / base, 2),
            # 純 clock gating 的效果（控制掉改寫之後）
            "cg_only_pct": round(100 * (cg - rtlv) / rtlv, 2),
        })
    if arows:
        run.csv("results_m9_area.csv", list(arows[0].keys()), arows)

    print("\n=== 三態的功耗 vs SNR")
    for r in rows:
        print(f"  {r['label']:16s} "
              f"{r['p_1db_mw']:7.3f} {r['p_2db_mw']:7.3f} {r['p_3db_mw']:7.3f} "
              f"{r['p_4db_mw']:7.3f} {r['p_5db_mw']:7.3f}  |  "
              f"全距 {r['range_pct']:5.2f}% ({r['range_abs_mw']:.4f} mW)  "
              f"R² {r['r2']:.3f}  σ_null {r['sigma_null_mw'] or float('nan'):.4f}  "
              f"t {r['t_slope'] if r['t_slope'] is not None else float('nan'):+.2f}  "
              f"-> {r['frozen_verdict']}")

    print("\n=== 事前預測的裁決")
    print(f"  P1 降幅 < 10%     -> **推翻**（實測 {d_tot:+.1f}%）")
    print(f"  P2 null 存活      -> **未解析**（凍結判準第三列）")
    print(f"  P3 面積上升        -> **推翻**（實測 -9.35% 到 -12.10%）")
    print("  P4/P5（memory traceback）-> 尚未執行")

    return run.finalize()


if __name__ == "__main__":
    sys.exit(main())
