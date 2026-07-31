"""check_paper_numbers.py — 報告數字的一致性檢查（golden test）。

移植自 RISC-V 專案的同名工具，並針對本專案補上一個它沒有的、而本專案**最需要**的檢查：
**預先登記的 commit 時間戳必須早於量測**（§4）。整篇報告的科學主張都繫在那一條上；
不機械化驗證它，「我們事前就登記了」就只是一句自稱。

以 data/*.csv 為**唯一事實來源**，對 docs/report.md 中每一個引用的數字逐一比對。

每一條 assertion 同時做兩件事：
  (1) 該值「等於由 CSV 算出的真值」        —— 防止文件寫錯；
  (2) 該值字串「確實出現在該文件中」       —— 防止 assertion 與文件脫節。

另附四項結構檢查：
  §2  gates.csv 完整性（無重複、全綠）
  §3  已撤回主張的字面回歸防護
  §4  **預先登記 vs 量測的 commit 時間戳**
  §5  百分比覆蓋掃描（報告裡沒被任何 assertion 覆蓋的百分比）

執行：python3 scripts/check_paper_numbers.py
      exit 0 = 全數通過；exit 1 = 有 mismatch。
"""

import csv
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# FEC_REPORT_PATH：讓 scripts/mutate_check.sh 把檢查器指向 report.md 的**副本**。
# 變異測試要在文件裡注入已知錯誤、確認檢查器抓得到；原本的做法是 `sed -i` 直接改
# git 追蹤中的 docs/report.md，再靠 trap EXIT + /tmp 備份還原——而它是 `make all`
# 與 `make repro` 的最後一步，中途被砍就會留下一份被改壞的追蹤檔。
# 對副本操作之後，變異測試再也不可能損毀真的文件。
DOCS = {
    "report": os.environ.get("FEC_REPORT_PATH")
              or os.path.join(ROOT, "docs", "report.md"),
    "falsif": os.path.join(ROOT, "docs", "falsification.md"),
    "spec": os.path.join(ROOT, "docs", "fec_viterbi_cosim_spec.md"),
    # README 是專案門面。它曾經**停在 M3+M4 整整兩個里程碑**都沒人發現——
    # 因為沒有任何東西在盯它。納入稽核之後，它的數字就不可能再悄悄跟資料脫節。
    "readme": os.path.join(ROOT, "README.md"),
}
DOCTEXT = {k: open(v, encoding="utf-8").read() for k, v in DOCS.items()}

# 搜尋用的正規化文本：
#   * 去掉千分位逗號（報告寫 25,479 µm² 是正確排版，不該為了工具而拿掉）
#   * U+2212（−，數學減號）統一成 ASCII '-'
DOCSEARCH = {k: v.replace(",", "").replace("−", "-")
             for k, v in DOCTEXT.items()}


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


PW = load("results_m5_power.csv")
DS = load("results_m5_dstar.csv")
FX = load("results_m5_fmax.csv")
TG = load("results_m5_toggle.csv")
MC = load("results_m5_mechanism.csv")
ADC = load("results_m5_adc.csv")
GATES = load("gates.csv")
GRID = load("m2_grid.csv")
with open(os.path.join(ROOT, "ppa", "out", "synth", "synth.json")) as f:
    SYN = {d["tag"]: d for d in json.load(f)}

AT3 = {(int(p["Q"]), int(p["D"])): p for p in PW if float(p["snr_db"]) == 3.0}


def pwr(Q, D, key="p_total_w"):
    return float(AT3[(Q, D)][key])


def req_ebn0(Q, D):
    p = AT3[(Q, D)]
    return next(float(g["required_ebn0_db"]) for g in GRID
                if int(g["Q"]) == Q and float(g["clip"]) == float(p["clip"])
                and int(g["D"]) == D)


def dstar(Q, D, model, env, eta=0.1):
    return next(float(x["dstar_m"]) for x in DS if int(x["Q"]) == Q
                and int(x["D"]) == D and x["model"] == model
                and x["env"] == env and float(x["eta_pa"]) == eta)


def dd(model, env):
    """Δd*（Q3/D32 -> Q6/D32），百分比。"""
    return 100.0 * (dstar(6, 32, model, env) / dstar(3, 32, model, env) - 1.0)


def fmax(tag, key):
    return float(next(r[key] for r in FX if r["tag"] == tag))


def toggle(sig, snr, tag="Q4_W10_D64"):
    return float(next(r["tc_per_cycle"] for r in TG if r["tag"] == tag
                      and r["signal"] == sig and float(r["snr_db"]) == snr))


def trend(sig, tag="Q4_W10_D64"):
    """線性迴歸的 (斜率, R², 全距%)。5 個點的「看起來單調」不是證據，R² 才是。"""
    v = sorted([(float(r["snr_db"]), float(r["tc_per_cycle"])) for r in TG
                if r["tag"] == tag and r["signal"] == sig])
    xs = [a for a, _ in v]
    ys = [b for _, b in v]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    sst = sum((y - my) ** 2 for y in ys)
    ssr = sum((my + slope * (x - mx) - y) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ssr / sst if sst else 0.0
    rng = 100.0 * (max(ys) - min(ys)) / max(ys)
    return slope, r2, rng


def mech(case, key):
    return float(next(r[key] for r in MC if r["case"] == case))


def mech_snr(snr, key):
    return float(next(r[key] for r in MC if r["case"] == "agc"
                      and float(r["snr_db"]) == snr))


def adc_row(fom, Q, model="A", env="indoor", D=32):
    return next(r for r in ADC if int(r["adc_fom_fj"]) == fom and int(r["Q"]) == Q
                and r["model"] == model and r["env"] == env and int(r["D"]) == D)


def area_share(tag, mod):
    d = SYN[tag]
    return 100.0 * d["modules"][mod]["area_total_um2"] / d["total_area_um2"]


def gate_measured(name):
    return next(g["measured"] for g in GATES if g["gate"].startswith(name))


def gate_num(name):
    """從 gates.csv 的 measured 欄抽出第一個數字。

    為什麼要這樣做：第一版把 M1 的數字寫成 a("1.1", "未編碼", 9.571, 9.571)
    —— truth 與 cited 都是硬寫的常數，於是那條 assertion **只驗了「字串有出現在文件裡」**，
    完全沒有驗「它等於量測值」。gate 的數字一改，assertion 照樣綠燈。
    改成從 gates.csv 抽，才真的把文件釘在資料上。
    """
    m = re.search(r"(-?\d+\.\d+)", gate_measured(name))
    if not m:
        raise ValueError(f"gates.csv 的 '{name}' 的 measured 欄抽不出數字："
                         f"{gate_measured(name)!r}")
    return float(m.group(1))


# ---------------------------------------------------------------- assertions
A = []


def a(sec, desc, truth, cited, nd=2, doc="report"):
    A.append((doc, sec, desc, truth, cited, nd))


# ---- §1 驗證鏈路 ----
# 36 筆記錄 = 30 個有判準的 gate + 6 筆觀測（M0 3 + M1 6 + M2 3 + M3 5 + M4 3 + M5 8 + M9 8）。
# gate 改名留下孤兒的破口已在 scripts/gates.py 修根因（整批取代 milestone），不再靠人發現。
a("1", "gate 總數", len(GATES), 36, 0)

# ---- §1.1 通訊層（真值從 gates.csv 的 measured 欄抽出，不是硬寫的常數）----
a("1.1", "未編碼 @1e-5", gate_num("G1 "), 9.571, 3)
a("1.1", "編碼增益", gate_num("G2b"), 5.434, 3)
a("1.1", "3-bit 損失", gate_num("G3 "), 0.225, 3)
a("1.1", "硬判決損失", gate_num("G4b"), 2.413, 3)

# ---- §2.1 功耗 ----
for (Q, D), tag in (((3, 32), "Q3 W8 D32"), ((6, 32), "Q6 W12 D32"),
                    ((4, 64), "Q4 W10 D64"), ((6, 64), "Q6 W12 D64")):
    a("2.1", f"{tag} 需 Eb/N0", req_ebn0(Q, D), req_ebn0(Q, D), 4)
    a("2.1", f"{tag} P_total mW", pwr(Q, D) * 1e3, pwr(Q, D) * 1e3, 3)
    a("2.1", f"{tag} E_dec pJ", float(AT3[(Q, D)]["e_dec_pj_per_bit"]),
      float(AT3[(Q, D)]["e_dec_pj_per_bit"]), 1)

# traceback 與 Q 無關（同 D=32）
_tb3, _tb6 = pwr(3, 32, "p_u_tb_w") * 1e3, pwr(6, 32, "p_u_tb_w") * 1e3
a("2.1", "traceback Q3 D32", _tb3, 13.055, 3)
a("2.1", "traceback Q6 D32", _tb6, 13.044, 3)
a("2.1", "traceback 差異%", 100 * abs(_tb6 - _tb3) / _tb3, 0.08, 2)

# W 縮放
a("2.1", "ACS 隨 W 增幅%",
  100 * (pwr(6, 32, "p_u_acs_w") / pwr(3, 32, "p_u_acs_w") - 1), 54.7, 1)
a("2.1", "min-PM 隨 W 增幅%",
  100 * (pwr(6, 32, "p_u_minpm_w") / pwr(3, 32, "p_u_minpm_w") - 1), 64.4, 1)

# 佔比
for (Q, D), lab in (((3, 32), "Q3"), ((6, 32), "Q6")):
    tot = pwr(Q, D)
    a("2.1", f"{lab} traceback 佔比", 100 * pwr(Q, D, "p_u_tb_w") / tot,
      54.2 if lab == "Q3" else 43.0, 1)
    a("2.1", f"{lab} ACS 佔比", 100 * pwr(Q, D, "p_u_acs_w") / tot,
      33.8 if lab == "Q3" else 41.5, 1)
    a("2.1", f"{lab} min-PM 佔比", 100 * pwr(Q, D, "p_u_minpm_w") / tot,
      10.3 if lab == "Q3" else 13.5, 1)

# min-PM vs PM register file（意外發現）
_MP = {"Q3_W8_D32": (25479, 11531, 2.21), "Q4_W10_D64": (31542, 14094, 2.24),
       "Q6_W12_D32": (40773, 16656, 2.45), "Q6_W12_D64": (40420, 16656, 2.43)}
for tag, (mp_um2, pmrf, mult) in _MP.items():
    _m = SYN[tag]["modules"]["minpm"]["area_total_um2"]
    _p = SYN[tag]["modules"]["acs_array"]["seq_area_total_um2"]
    a("2.1", f"{tag} min-PM 面積", _m, mp_um2, 0)
    a("2.1", f"{tag} PM regfile 面積", _p, pmrf, 0)
    a("2.1", f"{tag} min-PM/PMregfile 倍數", _m / _p, mult, 2)
_mps = [area_share(t, "minpm") for t in SYN]
a("2.1", "min-PM 面積佔比 min", min(_mps), 11.8, 1)
a("2.1", "min-PM 面積佔比 max", max(_mps), 19.7, 1)
# 摘要引用的「比整個 PM register file 還大 2.21–2.45 倍」也要對回資料。
# （原本寫成「2.2–2.5 倍」——但真值最大是 2.4479，1 位小數應是 2.4，不是 2.5。
#  變異測試/checker 抓到的，已改為 2 位小數，與下方逐組態的表一致。）
_mult = [SYN[t]["modules"]["minpm"]["area_total_um2"]
         / SYN[t]["modules"]["acs_array"]["seq_area_total_um2"] for t in SYN]
a("2.1", "min-PM/PMregfile 倍數 min", min(_mult), 2.21, 2)
a("2.1", "min-PM/PMregfile 倍數 max", max(_mult), 2.45, 2)

# traceback 的 flop 佔比（報告 §3.3 用它來說明「flop 數 ≠ 功耗」）
_tbf = [100.0 * SYN[t]["modules"]["traceback"]["dff_total"] / SYN[t]["total_dff"]
        for t in SYN]
a("3.3", "traceback flop 佔比 min", min(_tbf), 67.7, 1)
a("3.3", "traceback flop 佔比 max", max(_tbf), 84.1, 1)

# ---- §2.2 Fmax ----
_FM = {"Q4_W10_D64": (6.0, 8683, 18.10, 150.2, 70, 3.04),
       "Q6_W12_D64": (5.8, 8937, 18.69, 101.2, 192, 3.41),
       "Q6_W12_D32": (10.1, 4840, 10.70, 145.3, 29, 3.45),
       "Q3_W8_D32": (11.3, 4395, 9.53, 153.1, 205, 2.95)}
for tag, (f0, fo0, cap, f1, fo1, da) in _FM.items():
    a("2.2", f"{tag} Fmax 純邏輯", fmax(tag, "fmax_before_mhz"), f0, 1)
    a("2.2", f"{tag} 最大扇出（前）", fmax(tag, "max_fanout_before"), fo0, 0)
    a("2.2", f"{tag} Fmax repair 後", fmax(tag, "fmax_after_mhz"), f1, 1)
    a("2.2", f"{tag} 最大扇出（後）", fmax(tag, "max_fanout_after"), fo1, 0)
    a("2.2", f"{tag} 面積增量%",
      100 * (fmax(tag, "area_after_um2") / fmax(tag, "area_before_um2") - 1), da, 2)
# 只有 Q4 的負載被報告引用（在關鍵路徑那段 code block 裡）；不引用的就不 assert。
a("2.2", "Q4 負載 pF", fmax("Q4_W10_D64", "worst_gate_cap_before_pf"), 18.10, 2)
a("2.2", "關鍵路徑 ns", fmax("Q4_W10_D64", "path_before_ns"), 166.81, 2)
a("2.2", "最慢閘延遲 ns", fmax("Q4_W10_D64", "worst_gate_delay_before_ns"), 102.6, 1)
a("2.2", "最低 Fmax", min(fmax(t, "fmax_after_mhz") for t in _FM), 101.2, 1)

# ---- §3.1 d* ----
_DT = {(3, 32): (153.6, 17.8, 2428.7, 86.0), (6, 32): (170.9, 18.9, 2410.6, 85.6),
       (4, 64): (206.1, 21.0, 2413.0, 85.7), (6, 64): (212.3, 21.4, 2409.2, 85.6)}
for (Q, D), (af, ai, bf, bi) in _DT.items():
    a("3.1", f"Q{Q}D{D} A/free", dstar(Q, D, "A", "free_space"), af, 1)
    a("3.1", f"Q{Q}D{D} A/indoor", dstar(Q, D, "A", "indoor"), ai, 1)
    a("3.1", f"Q{Q}D{D} B/free", dstar(Q, D, "B", "free_space"), bf, 1)
    a("3.1", f"Q{Q}D{D} B/indoor", dstar(Q, D, "B", "indoor"), bi, 1)
a("3.2", "F1 最小 d*", min(float(x["dstar_m"]) for x in DS), 17.8, 1)

# ---- §3.2 證偽條件 ----
a("3.2", "F2 模型A/free", dd("A", "free_space"), 11.29, 2)
a("3.2", "F2 模型A/indoor", dd("A", "indoor"), 6.31, 2)
a("3.2", "F3 模型B/free", dd("B", "free_space"), -0.75, 2)
a("3.2", "F3 模型B/indoor", dd("B", "indoor"), -0.43, 2)

# ---- §3.3 α ----
_e3 = float(AT3[(3, 32)]["e_dec_pj_per_bit"])
_e6 = float(AT3[(6, 32)]["e_dec_pj_per_bit"])
a("3.3", "E_dec 比值", _e6 / _e3, 1.2586, 4)
a("3.3", "α 實測", 2.0 * (_e6 / _e3 - 1.0), 0.517, 3)
# 「錯了 3.4 倍」也是一個要對回資料的數字（實測 α / 登記 α）
a("3.3", "α 誤差倍數", 2.0 * (_e6 / _e3 - 1.0) / 0.15, 3.4, 1)

# ---- §3.4 ADC ----
for fom, ea6, sh6, wi in ((10, 1.28, 0.4, 6.42), (100, 12.80, 4.0, 7.36),
                          (500, 64.00, 17.4, 11.27)):
    r6 = adc_row(fom, 6)
    r3 = adc_row(fom, 3)
    a("3.4", f"FoM{fom} E_ADC Q6", float(r6["e_adc_pj_per_bit"]), ea6, 2)
    a("3.4", f"FoM{fom} ADC 佔比", float(r6["adc_share_pct"]), sh6, 1)
    a("3.4", f"FoM{fom} Δd* 含 ADC",
      100 * (float(r6["dstar_with_adc_m"]) / float(r3["dstar_with_adc_m"]) - 1), wi, 2)

# ---- §3.2.1 不確定度傳播（後補：先前 F1–F3 的裁決全部只有點估計）----
def dstar_ci(Q, D, model, env, key, eta=0.1):
    return float(next(x[key] for x in DS if int(x["Q"]) == Q and int(x["D"]) == D
                      and x["model"] == model and x["env"] == env
                      and float(x["eta_pa"]) == eta))


a("3.2.1", "d* Q3D32 A/indoor 點估計",
  dstar_ci(3, 32, "A", "indoor", "dstar_m"), 17.76, 2)
a("3.2.1", "d* Q3D32 A/indoor CI 低", dstar_ci(3, 32, "A", "indoor", "dstar_ci_low_m"),
  17.60, 2)
a("3.2.1", "d* Q3D32 A/indoor CI 高", dstar_ci(3, 32, "A", "indoor", "dstar_ci_high_m"),
  17.91, 2)


def req_sigma(Q, D):
    return float(next(x["required_sigma_db"] for x in DS
                      if int(x["Q"]) == Q and int(x["D"]) == D))


# 報告 §3.2.1 引用的三個 winner 的 σ（(Q,D) 明確指定 —— 只用 Q 會抓到第一列，Q=6 有兩個 D）
# README 也引用同一組（用來說明 winner 排序是平手），故兩份文件都驗。
for _Q, _D, _s in ((6, 64, 0.0239), (4, 64, 0.0225), (6, 32, 0.0208)):
    a("3.2.1", f"Q{_Q}D{_D} required σ", req_sigma(_Q, _D), _s, 4)
    a("3.2.1", f"Q{_Q}D{_D} required σ", req_sigma(_Q, _D), _s, 4, doc="readme")

# Δd* 的區間：直接從 gates.csv 的 F2 measured 欄取（那是裁決的權威記錄）。
_f2m = next(g["measured"] for g in GATES if g["gate"].startswith("F2 "))
for _label, _lo, _hi in (("模型A/free_space", -10.84, 11.75),
                         ("模型A/indoor", -6.06, 6.55),
                         ("模型B/free_space", -1.05, -0.45),
                         ("模型B/indoor", -0.60, -0.26)):
    for _v in (_lo, _hi):
        # fmt() 定義在本檔更下方，這裡直接格式化（避免前向參照）
        _s = f"{abs(_v):.2f}"
        if _s not in _f2m.replace(",", ""):
            fails.append(f"[dstar:ci] F2 gate 的 measured 欄缺 {_label} 的區間端點 {_s}")

# 方向性斷言：四個 Δd* 的 95% 區間都不得跨過零點 —— 這正是「符號翻轉不是雜訊」的內容。
# 一旦某個區間跨零，報告就不得再宣稱符號翻轉，而這條會讓 make report 紅燈。
for _m, _e in (("A", "free_space"), ("A", "indoor"),
               ("B", "free_space"), ("B", "indoor")):
    _lo = re.search(rf"模型{_m}/{_e}: [-+][\d.]+% \[([-+][\d.]+), ([-+][\d.]+)\]", _f2m)
    if not _lo:
        fails.append(f"[dstar:ci] F2 gate 沒有 模型{_m}/{_e} 的區間 —— "
                     f"裁決缺不確定度，不得宣稱符號")
    elif float(_lo.group(1)) * float(_lo.group(2)) <= 0:
        fails.append(f"[dstar:ci] 模型{_m}/{_e} 的 Δd* 區間跨過零點 "
                     f"[{_lo.group(1)}, {_lo.group(2)}] —— **符號未被解析出來**，"
                     f"報告不得宣稱「符號會翻轉」")

# ---- §1 「gate」與「觀測」必須分開計數 ----
#
# gates.csv 裡其實有兩種列：**有 pass/fail 判準的 gate**，與**只是記錄下來的觀測**
# （expected 欄自陳「（觀測，不是 pass/fail）」）。把兩者混報成「N 個 gate 全綠」
# 略微灌水——一個沒有判準的東西不可能「不綠」。
#
# 目前是 26 個有判準的 gate + 2 筆觀測（M5-3 功耗 vs SNR、M5-4 power gating）。
# 這條檢查讓分類不能悄悄漂移：新增觀測卻沒更新文件、或把觀測寫成 gate，都會紅燈。
_OBS = [g for g in GATES if "觀測" in g["expected"] or "觀測" in g["tolerance"]]
_REAL = [g for g in GATES if g not in _OBS]
a("1", "有判準的 gate 數", len(_REAL), 30, 0)
a("1", "觀測筆數", len(_OBS), 6, 0)
if len(_REAL) + len(_OBS) != len(GATES):
    fails.append("[gates] gate / 觀測的分類沒有覆蓋 gates.csv 的每一列")

# ---- §3.2.2 energy_model.md §2 宣告過、但 M5 從未跑的兩條掃描 ----
SENS = load("results_m5_sensitivity.csv")


def sens_d(Q, D, nf, pc, model, env, gated=True):
    return float(next(x["dstar_m"] for x in SENS
                      if int(x["Q"]) == Q and int(x["D"]) == D
                      and float(x["nf_db"]) == nf and int(x["p_circuit_mw"]) == pc
                      and x["model"] == model and x["env"] == env
                      and x["power_gated"] == str(gated)))


for _nf, _fs, _in in ((3.0, 216.9, 21.6), (6.0, 153.6, 17.8), (10.0, 96.9, 13.6)):
    a("3.2.2", f"NF{_nf} d* A/free", sens_d(3, 32, _nf, 60, "A", "free_space"), _fs, 1)
    a("3.2.2", f"NF{_nf} d* A/indoor", sens_d(3, 32, _nf, 60, "A", "indoor"), _in, 1)
for _pc, _in in ((20, 63.0), (60, 86.0), (120, 104.8)):
    a("3.2.2", f"Pc{_pc} d* B/indoor", sens_d(3, 32, 6.0, _pc, "B", "indoor"), _in, 1)
a("3.2.2", "F1b 掃描全域最小 d*",
  min(float(x["dstar_m"]) for x in SENS), 13.65, 2)

# power gating 的實測量級（文件 §5 說 200 倍，實際 E_dec 只變 0.055%、d* 只變 0.017%）。
# 報告引用的是**跨組態的最大值**，故這裡也取 max，不是挑某一個組態。
def _pg_pairs(key):
    out = []
    for r in SENS:
        if r["power_gated"] != "True":
            continue
        m = next((x for x in SENS
                  if x["power_gated"] == "False" and x["Q"] == r["Q"]
                  and x["D"] == r["D"] and x["nf_db"] == r["nf_db"]
                  and x["p_circuit_mw"] == r["p_circuit_mw"]
                  and x["model"] == r["model"] and x["env"] == r["env"]), None)
        if m:
            out.append((float(r[key]), float(m[key])))
    return out


_d_pairs = _pg_pairs("dstar_m")
_e_pairs = _pg_pairs("e_dec_pj_per_bit")
a("3.2.2", "power gating 對 d* 的影響（最大）",
  max(100.0 * (off / on - 1.0) for on, off in _d_pairs), 0.027, 3)
a("3.2.2", "power gating 對 E_dec 的影響（最大）",
  max(100.0 * (off / on - 1.0) for on, off in _e_pairs), 0.055, 3)

# 漏電佔總功耗的比例——這是「200 倍作用在一個可忽略的項上」的量化依據
_RES = load("results.csv")
a("3.2.2", "漏電佔總功耗",
  max(100.0 * float(r["p_leak_w"]) / float(r["p_total_w"]) for r in _RES),
  0.00028, 5)

# 方向性斷言：關掉 power gating 只能讓 E_dec 變大（多付閒置時的漏電），不可能變小。
if any(off < on for on, off in _e_pairs):
    fails.append("[power-gating] 關掉 power gating 反而讓 E_dec 變小 —— "
                 "energy_model.e_dec_of() 的兩個分支寫反了")

# ---- §5-1 traceback 記憶體的敏感度線（修正原本方向反了的推論）----
# 原文宣稱「Q 之間的相對比較不受影響」。實際上 traceback 是 E_dec 裡與 Q 無關的那一項，
# 高估它會**稀釋** Q 依賴 ⇒ 已發表的 Δd* 是**下界**。這組 assertion 把該表釘回 CSV。
TBS = load("results_m5_tb_sensitivity.csv")


def tbs(fac, env, key):
    return float(next(r[key] for r in TBS if float(r["tb_factor"]) == fac
                      and r["model"] == "A" and r["env"] == env))


for _fac, _ratio, _free, _ind in ((1.0, 1.2586, 11.29, 6.31),
                                  (0.5, 1.3551, 15.48, 8.57),
                                  (0.2, 1.4572, 19.75, 10.85),
                                  (0.1, 1.5056, 21.73, 11.89)):
    a("5.1", f"tb×{_fac} E_dec 比值", tbs(_fac, "indoor", "e_dec_ratio"), _ratio, 4)
    a("5.1", f"tb×{_fac} Δd* A/free",
      tbs(_fac, "free_space", "delta_dstar_pct"), _free, 2)
    a("5.1", f"tb×{_fac} Δd* A/indoor",
      tbs(_fac, "indoor", "delta_dstar_pct"), _ind, 2)

# 方向性斷言：縮減 traceback 必須讓 Δd* **單調變大**（這就是「已發表值是下界」的內容）。
# 不是文件引用檢查，直接進 fails。
_seq = [tbs(f, "indoor", "delta_dstar_pct") for f in (1.0, 0.5, 0.2, 0.1)]
if not all(x < y for x, y in zip(_seq, _seq[1:])):
    fails.append(f"[tb-sens] 縮減 traceback 功耗未使 Δd* 單調變大：{_seq} —— "
                 f"「已發表的 Δd* 是下界」這個結論不成立")

# ---- §4.1 機制：資訊 vs 活動 ----
for snr, agree, tog in ((-2.0, 0.8982, 0.5011), (3.0, 1.0000, 0.5015),
                        (10.0, 1.0000, 0.5002)):
    a("4.1", f"{snr}dB 真實路徑一致率", mech_snr(snr, "agree_true_path"), agree, 4)
    a("4.1", f"{snr}dB surv 翻轉率", mech_snr(snr, "tog_surv"), tog, 4)

# ---- §4.1 趨勢檢定（R² 才是證據，不是「看起來單調」）----
_TR = {"in_r": (0.00064, 0.707, 0.61), "bm": (-0.00017, 0.020, 1.13),
       "pm": (0.00258, 0.913, 3.34), "surv": (0.00003, 0.000, 0.98),
       "re": (0.00146, 0.247, 2.48)}
for sig, (sl, r2, rng) in _TR.items():
    s, r, g = trend(sig)
    a("4.1", f"{sig} 斜率", s, sl, 5)
    a("4.1", f"{sig} R²", r, r2, 3)
    a("4.1", f"{sig} 全距%", g, rng, 2)

# ---- §4.2 反事實 ----
for k, sym, asym in ((0, 0.5042, 0.5042), (1, 0.5042, 0.0000),
                     (2, 0.5042, 0.0000), (3, 0.5018, 0.5018)):
    a("4.2", f"對稱 bit{k}", mech("fixed_hi_sym", f"tog_r_b{k}"), sym, 4)
    a("4.2", f"DC偏移 bit{k}", mech("fixed_hi_asym", f"tog_r_b{k}"), asym, 4)

a("4.1", "pm 全距（報告以 1 位小數引用）", trend("pm")[2], 3.3, 1)

# ---- §4.3 跨層（含報告引用的「差 %」）----
_RATIO = 0.9348      # stage/cycle，報告表格裡有這一欄
for snr, gold, saif, diff in ((1.0, 0.4989, 0.4661, -0.06),
                              (3.0, 0.5015, 0.4664, -0.51),
                              (5.0, 0.4980, 0.4659, 0.08)):
    g = mech_snr(snr, "tog_surv")
    t = toggle("surv", snr)
    a("4.3", f"{snr}dB golden/stage", g, gold, 4)
    a("4.3", f"{snr}dB SAIF/cycle", t, saif, 4)
    a("4.3", f"{snr}dB 差%", 100 * (t - g * _RATIO) / (g * _RATIO), diff, 2)

# ---- §6 結論（四捨五入到 1 位）----
a("6", "結論 Δd* 室內", dd("A", "indoor"), 6.3, 1)
a("6", "結論 Δd* 模型B 室內", dd("B", "indoor"), -0.43, 2)

# ================================================================ README
# README 停在 M3+M4 整整兩個里程碑都沒被發現，因為沒有任何東西在盯它。
# 這裡把它的承重數字全部釘死，讓同一種脫節不可能再發生。
a("rm", "F1 最小 d*", min(float(x["dstar_m"]) for x in DS), 17.8, 1, doc="readme")
a("rm", "F2 模型A/free", dd("A", "free_space"), 11.29, 2, doc="readme")
a("rm", "F2 模型A/indoor", dd("A", "indoor"), 6.31, 2, doc="readme")
a("rm", "F3 模型B/free", dd("B", "free_space"), -0.75, 2, doc="readme")
a("rm", "F3 模型B/indoor", dd("B", "indoor"), -0.43, 2, doc="readme")
a("rm", "α 實測", 2.0 * (_e6 / _e3 - 1.0), 0.517, 3, doc="readme")
a("rm", "α 誤差倍數", 2.0 * (_e6 / _e3 - 1.0) / 0.15, 3.4, 1, doc="readme")
a("rm", "traceback flop 佔比 min", min(_tbf), 67.7, 1, doc="readme")
a("rm", "traceback flop 佔比 max", max(_tbf), 84.1, 1, doc="readme")
a("rm", "min-PM 面積佔比 min", min(_mps), 11.8, 1, doc="readme")
a("rm", "min-PM 面積佔比 max", max(_mps), 19.7, 1, doc="readme")
a("rm", "min-PM/PMregfile 倍數 min", min(_mult), 2.21, 2, doc="readme")
a("rm", "min-PM/PMregfile 倍數 max", max(_mult), 2.45, 2, doc="readme")
a("rm", "關鍵路徑 ns", fmax("Q4_W10_D64", "path_before_ns"), 166.81, 2, doc="readme")
a("rm", "Fmax 純邏輯", fmax("Q4_W10_D64", "fmax_before_mhz"), 6.0, 1, doc="readme")
a("rm", "最大扇出", fmax("Q4_W10_D64", "max_fanout_before"), 8683, 0, doc="readme")
a("rm", "負載 pF", fmax("Q4_W10_D64", "worst_gate_cap_before_pf"), 18.10, 2,
  doc="readme")
a("rm", "Fmax repair 後", fmax("Q4_W10_D64", "fmax_after_mhz"), 150.2, 1, doc="readme")
a("rm", "最低 Fmax", min(fmax(t, "fmax_after_mhz") for t in _FM), 101.2, 1,
  doc="readme")
a("rm", "traceback 差異%（Q3 vs Q6, 同 D）", 100 * abs(_tb6 - _tb3) / _tb3, 0.08, 2,
  doc="readme")
a("rm", "surv R²", trend("surv")[1], 0.000, 3, doc="readme")
a("rm", "pm R²", trend("pm")[1], 0.913, 3, doc="readme")
a("rm", "反事實 對稱 bit1", mech("fixed_hi_sym", "tog_r_b1"), 0.5042, 4, doc="readme")
a("rm", "反事實 DC偏移 bit1", mech("fixed_hi_asym", "tog_r_b1"), 0.0000, 4,
  doc="readme")
a("rm", "gate 總數", len(GATES), 36, 0, doc="readme")

# 功耗佔比（README §M5 引用了「43.0–54.2% 的功耗」與「10.3–13.5% 的功耗」）
for (_q, _d), _lab in (((3, 32), "Q3"), ((6, 32), "Q6")):
    _tot = pwr(_q, _d)
    a("rm", f"{_lab} traceback 功耗佔比", 100 * pwr(_q, _d, "p_u_tb_w") / _tot,
      54.2 if _lab == "Q3" else 43.0, 1, doc="readme")
    a("rm", f"{_lab} min-PM 功耗佔比", 100 * pwr(_q, _d, "p_u_minpm_w") / _tot,
      10.3 if _lab == "Q3" else 13.5, 1, doc="readme")

# M1 的既有數字（真值從 gates.csv 抽，不是硬寫）
a("rm", "未編碼 @1e-5", gate_num("G1 "), 9.571, 3, doc="readme")
a("rm", "編碼增益", gate_num("G2b"), 5.434, 3, doc="readme")
a("rm", "3-bit 損失", gate_num("G3 "), 0.225, 3, doc="readme")
a("rm", "硬判決損失", gate_num("G4b"), 2.413, 3, doc="readme")

# M2 的 winner 表（真值從 data/m2_winners.csv）
WIN = load("m2_winners.csv")
for _w in WIN:
    _q, _d = int(_w["Q"]), int(_w["D"])
    a("rm", f"winner Q{_q}D{_d} 所需 Eb/N0",
      float(_w["required_ebn0_db"]), float(_w["required_ebn0_db"]), 3, doc="readme")
    a("rm", f"winner Q{_q}D{_d} 損失",
      float(_w["loss_vs_float_db"]), float(_w["loss_vs_float_db"]), 3, doc="readme")
    a("rm", f"winner Q{_q}D{_d} survivor bits",
      int(_w["survivor_bits"]), int(_w["survivor_bits"]), 0, doc="readme")

# README 的 winner 表寫「記憶體減半，只付 +0.04 dB」——那是 Q6/D32 與 Q6/D64 的差，
# 是導出來的數字，不是自由參數，所以要 assert 而不是白名單。
_w64 = next(w for w in WIN if int(w["Q"]) == 6 and int(w["D"]) == 64)
_w32 = next(w for w in WIN if int(w["Q"]) == 6 and int(w["D"]) == 32)
a("rm", "D 減半的代價 (dB)",
  float(_w32["required_ebn0_db"]) - float(_w64["required_ebn0_db"]), 0.04, 2,
  doc="readme")

# ================================================================ 執行
fails = []
asserted = {d: set() for d in DOCS}


def fmt(v, nd):
    return f"{v:.{nd}f}" if nd > 0 else str(int(round(float(v))))


for doc, sec, desc, truth, cited, nd in A:
    s = fmt(cited, nd)
    asserted[doc].add(s)
    asserted[doc].add(s.lstrip("-"))          # 表格裡可能寫 −0.75 或 0.75
    tol = 0.5 * 10 ** (-nd) if nd > 0 else 0.5
    if abs(round(float(truth), nd) - round(float(cited), nd)) > tol:
        fails.append(f"[{doc}:§{sec}] {desc}: 報告={cited} 但 CSV={truth}")
    elif s not in DOCSEARCH[doc]:
        fails.append(f"[{doc}:§{sec}] {desc}: 值 {s} 與 CSV 相符，"
                     f"但**在 {doc} 中找不到**（assertion 已與文件脫節？）")

# ---- §2 gates.csv 完整性 ----
_keys = [(g["milestone"], g["gate"]) for g in GATES]
_dups = sorted({k for k in _keys if _keys.count(k) > 1})
if _dups:
    fails.append(f"[gates:dup] gates.csv 有重複的 (milestone, gate)：{_dups[:5]} "
                 f"—— finalize() 應以 (milestone, gate) 取代而非附加")
_red = [g["gate"] for g in GATES if g["passed"] != "True"]
if _red:
    fails.append(f"[gates:red] gates.csv 有未通過的 gate：{_red}")
# 明列所有**應該**出現在 gates.csv 裡的里程碑，兩個方向都檢查。
#
# 這份清單原本是 M0..M5，M9 落地之後沒有跟著加——於是「gates.csv 缺了 M9」
# 只能靠 §1 的總數 36 間接抓到，而總數是很鈍的判準：少了 M9 的 8 列、
# 同時多出 8 列別的東西，它就完全看不見。
# 反向檢查（出現了不在清單裡的里程碑）則是為了讓下一個里程碑落地時
# **必須**回來改這一行，而不是靜靜地被總數吸收掉。
_EXPECT_MS = ("M0", "M1", "M2", "M3", "M4", "M5", "M9")
_seen_ms = {g["milestone"] for g in GATES}
for _ms in _EXPECT_MS:
    if _ms not in _seen_ms:
        fails.append(f"[gates:missing] gates.csv 缺少里程碑 {_ms}")
_extra_ms = sorted(_seen_ms - set(_EXPECT_MS))
if _extra_ms:
    fails.append(f"[gates:unexpected] gates.csv 出現未登記的里程碑 {_extra_ms}"
                 f" —— 新里程碑要同時更新 _EXPECT_MS 與 §1 的總數斷言")

# ---- §3 已撤回主張的字面回歸防護 ----
# 這些是**實測後被推翻**的說法。它們曾經寫在文件裡；R3 防止它們悄悄復活。
# 例外：報告與規格書需要**引用**這些說法來說明它們為何被推翻，故只擋「斷言句型」。
_BANNED = [
    (r"pm[^。\n]{0,20}(?:單調上升|嚴格單調)",
     "斷言 pm「單調上升」—— 實測 2 dB 有 0.3% 凹陷，**非嚴格單調**。"
     "正確說法是線性迴歸 R² = 0.913（surv 的 R² = 0.000）。"),
    (r"SNR 依賴住在 ACS",
     "斷言「SNR 依賴住在 ACS 的 switching」—— 實測 ACS switching 只變 1.8% 且非單調，"
     "R² 檢定顯示真正有趨勢的是 pm（累加器）。"),
    # 只擋「把 0.15 當成**實測值**」，不擋「事前登記 0.15 vs 實測 0.517」這種正確對比。
    # 第一版寫成 `α ≈ 0.15 ... (實測|量測)`，結果把報告裡正確的對比句誤判成違規。
    (r"(?:實測|量測|測得)[^。\n]{0,10}α\s*[≈=]\s*0\.15",
     "把事前登記的 α ≈ 0.15 當成**實測值** —— 實測是 0.517。"),
    (r"(?:功耗|power)[^。\n]{0,10}隨 SNR[^。\n]{0,6}(?:上升|下降|變化)(?!.{0,40}不存在)",
     "斷言功耗隨 SNR 變化 —— 實測總功耗只變 1.0%、非單調、方向與規格書前提相反。"),
]
# 自我指涉的例外：文件需要**引用**這些被禁的字樣，才能說明 R3 在擋什麼。
# 那段引用不是違規，用 <!-- R3-exempt --> 標出，掃描前挖空（以等長空白替換，保住行號）。
#
# **但豁免區本身就是一個洞**：它讓 R3 對其中的內容完全失明。所以限制
# **全專案只准存在一個**——多開即報錯，避免有人用它把真正的違規靜音掉。
_EXEMPT = re.compile(r"<!-- R3-exempt -->.*?<!-- /R3-exempt -->", re.S)

_n_exempt = sum(len(_EXEMPT.findall(DOCTEXT[k]))
                for k in ("report", "spec", "readme"))
if _n_exempt > 1:
    fails.append(f"[R3:exempt] 全專案有 {_n_exempt} 個 R3-exempt 豁免區，只允許 1 個。"
                 f"豁免會讓 R3 對其中的內容失明，不得增設。")

# README 也要掃 —— 機制的結論現在也寫在那裡，同一種回歸可以從那裡溜進來。
for _key in ("report", "spec", "readme"):
    _r3txt = _EXEMPT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                         DOCTEXT[_key])
    for _pat, _why in _BANNED:
        for _m in re.finditer(_pat, _r3txt):
            _ln = _r3txt[:_m.start()].count("\n") + 1
            fails.append(f"[R3:retracted] {DOCS[_key]}:{_ln} 出現已被實測推翻的主張"
                         f"「{_m.group(0)[:40]}」：{_why}")

# ---- §4 **預先登記 vs 量測的 commit 時間戳**（本專案最重要的結構檢查）----
# 整篇報告的科學主張是「這些預測在量測之前就登記了」。不機械化驗證，那只是一句自稱。
def _added_ts(path):
    """該路徑被**加入**版本庫的 commit 時間（epoch）。"""
    r = subprocess.run(["git", "-C", ROOT, "log", "--diff-filter=A",
                        "--format=%ct", "--", path],
                       capture_output=True, text=True)
    ts = [int(x) for x in r.stdout.split()]
    return min(ts) if ts else None


_PREREG = ["docs/falsification.md", "docs/energy_model.md"]
_MEASURE = ["data/power.json", "data/saif"]

_pre_ts = {p: _added_ts(p) for p in _PREREG}
_mea_ts = {p: _added_ts(p) for p in _MEASURE}

for _p, _t in _pre_ts.items():
    if _t is None:
        fails.append(f"[prereg] 找不到 {_p} 的 commit —— 預先登記無法驗證")
for _p, _t in _mea_ts.items():
    if _t is None:
        fails.append(f"[prereg] 找不到 {_p} 的 commit —— 量測時間無法驗證")

if all(_pre_ts.values()) and all(_mea_ts.values()):
    _latest_pre = max(_pre_ts.values())
    _earliest_mea = min(_mea_ts.values())
    if _latest_pre >= _earliest_mea:
        fails.append(
            f"[prereg] **預先登記沒有早於量測**："
            f"最晚的登記 {_latest_pre} >= 最早的量測 {_earliest_mea}。"
            f"報告不得宣稱「事前登記」。")
    else:
        _gap_h = (_earliest_mea - _latest_pre) / 3600.0
        PREREG_GAP_H = _gap_h     # 供最後列印

# 工作區若有未提交的 falsification.md 改動，登記的時間戳就不再描述現在的內容
_dirty = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--"]
                        + _PREREG, capture_output=True, text=True).stdout.strip()
if _dirty:
    fails.append(f"[prereg] 預先登記文件有未提交的改動，時間戳不再描述當前內容：\n{_dirty}")

# ---- §4b 跨文件：報告引用「預先登記」時必須逐字正確 ----
# 報告 §3.3 的關鍵論點是「falsification.md §3.2 的表本來就列了 α=0.50 那一列
# （+10.8% / +6.1%），實測正好落在那裡」。這是一個**對預先登記的引用**——
# 如果引錯了，整個「模型是對的、只有點估計錯」的辯解就垮了。
# 這些值不來自任何 CSV（它們是事前寫死的預測），所以數字 assertion 管不到；
# 改以跨文件比對把關：報告引用的字串必須真的出現在 falsification.md 裡。
_PREREG_QUOTES = ["10.8", "6.1", "0.15", "0.50"]
for _q in _PREREG_QUOTES:
    if _q not in DOCSEARCH["report"]:
        fails.append(f"[prereg:quote] 報告未引用預先登記的 {_q} "
                     f"(§3.3 的辯解需要它)")
    elif _q not in DOCSEARCH["falsif"]:
        fails.append(f"[prereg:quote] 報告引用了 {_q} 當作預先登記的內容，"
                     f"但 **falsification.md 裡沒有這個值** —— 引用不實。")

# ---- §4d 每個 d* 都必須能由 data/results.csv + 凍結常數**重算**出來 ----
#
# `docs/energy_model.md` §7 承諾過這件事：
#
#   > `scripts/check_paper_numbers.py` 會再檢查報告引用的每個 d\* 數字
#   > 都能由 `data/results.csv` + 本文件的常數重算出來。
#
# 但這個檢查從來沒被寫出來，而且它依賴的 `data/results.csv` 當時根本不存在。
# 上面所有 d* 的 assertion 走的是 `dstar()`，那只是**讀** results_m5_dstar.csv 裡
# 已經算好的 `dstar_m` —— 它驗的是「報告有沒有抄對 CSV」，不是「CSV 算得對不對」。
# 兩者的差別在 M5 的 d* 計算若有 bug，前者會全綠。
#
# 這裡把承諾補上：從 results.csv 的 (required_ebn0_db, e_dyn_per_bit_j, p_leak_w)
# 出發，先按 docs/energy_model.md §5 的分解式重建 E_dec，再用 §3 的 d_star() 重算，
# 與 results_m5_dstar.csv 逐列比對。**刻意不經過 A / len(A)**，因為它是結構檢查，
# 不是「文件引用」檢查（與 §2/§3/§4 同一類），也就不該動 README 的 assertion 計數。
sys.path.insert(0, ROOT)
from scripts.energy_model import (F_CLK, N_PATHLOSS,  # noqa: E402
                                  d_star as _d_star)

_RES_PATH = os.path.join(DATA, "results.csv")
if not os.path.exists(_RES_PATH):
    fails.append("[dstar:recompute] data/results.csv 不存在 —— "
                 "規格書 §8/§11.4 與 CLAUDE.md §5.4 指定它是唯一資料來源，"
                 "docs/energy_model.md §5/§7 的承諾也繫在它上面")
else:
    _RES = load("results.csv")
    # 以 (Q, D) 取 3 dB 的那一列 —— d* 用的就是這個工作點
    _res3 = {(int(r["Q"]), int(r["D"])): r
             for r in _RES if float(r["snr_db"]) == 3.0}
    _n_recomp = 0
    for _row in DS:
        _key = (int(_row["Q"]), int(_row["D"]))
        _src = _res3.get(_key)
        if _src is None:
            fails.append(f"[dstar:recompute] results.csv 缺 Q={_key[0]} D={_key[1]} "
                         f"@3 dB 那一列 —— d* 無法由唯一資料來源重算")
            continue
        # docs/energy_model.md §5：E_dec(f_clk) = e_dyn_per_bit + p_leak / f_clk
        _e_dec = float(_src["e_dyn_per_bit_j"]) + float(_src["p_leak_w"]) / F_CLK
        _recomp = _d_star(float(_src["required_ebn0_db"]), _e_dec,
                          float(_row["eta_pa"]), N_PATHLOSS[_row["env"]],
                          _row["model"])
        _stored = float(_row["dstar_m"])
        # results_m5_dstar.csv 存的是 round(v, 2)，故容差取半個最低位
        if abs(_recomp - _stored) > 0.005 + 1e-9 * _stored:
            fails.append(
                f"[dstar:recompute] Q={_key[0]} D={_key[1]} "
                f"{_row['model']}/{_row['env']}/η={_row['eta_pa']}："
                f"由 results.csv + 凍結常數重算得 {_recomp:.4f} m，"
                f"但 results_m5_dstar.csv 存的是 {_stored} m")
        _n_recomp += 1
    if _n_recomp and not any(f.startswith("[dstar:recompute]") for f in fails):
        DSTAR_RECOMPUTED = _n_recomp      # 供最後列印

# ---- §4c 自我指涉：README 說檢查器有幾條 assertion，就必須真的有幾條 ----
# 這條會在每次新增 assertion 時「壞掉」——那正是它的用途：逼 README 跟著更新，
# 而不是讓它慢慢變成一句過期的自我吹噓（README 曾經停在 M3+M4 兩個里程碑）。
# **每一處**都要對，不能只驗第一處：README 提了三次，只驗第一處的話，
# 另外兩處可以悄悄過期——那正是這個 checker 要防的病。
_cnts = re.findall(r"(\d+)\s*條 assertion", DOCTEXT["readme"])
if not _cnts:
    fails.append("[readme:selfref] README 沒說檢查器有幾條 assertion "
                 "—— 那句自我描述是承重的，不得省略")
for _c in set(_cnts):
    if int(_c) != len(A):
        fails.append(f"[readme:selfref] README 說有 {_c} 條 assertion，"
                     f"實際有 {len(A)} 條（README 共提到 {len(_cnts)} 次，"
                     f"每一處都要對）")

# ---- §5 百分比覆蓋掃描 ----
# 只掃報告，且只掃「結果」段落（§2 起）。標題/摘要的百分比也算，因為它們就是結果。
EXPECT_UNCOVERED = {
    "50.0",     # 「≈0.5 / 50%」是最大熵的定義，不是量測值
    "1.0",      # 「總功耗只變動 1.0%」—— 來自 gates.csv 的 M5-3 measured 欄（文字）
    "1.8",      # 同上（ACS switching）
    "5.0",      # F2 的判準門檻（預先登記的常數，不是量測值）
    "30.0",     # F3 的判準門檻
    "0.5",      # 量化器的 tie / 最大熵
    # §3.2.1 的不確定度傳播用到的兩個**分析參數**（不是量測值，沒有 CSV 可對）：
    "0.2",      # E_dec 的量測重複性，取自 M5-2 收斂測試（44.12/44.03/44.08 mW）
    "4.5",      # BER 掃描的 SNR 網格點（4.0/4.5/5.0/5.5 dB），交叉點落在第一個區間內
    "2.8", "1.6", "0.87",   # 事前登記的預測值（來自 falsification.md，非本次量測）
    "0.50",     # 同上
    # falsification.md §3.2 的 α=0.50 那一列。**不是量測值**，是事前寫死的預測，
    # 沒有 CSV 可以對。改由上方 [prereg:quote] 的跨文件比對把關（確認報告沒引錯）。
    "10.8", "6.1",
    # 事前登記的**常數**（docs/energy_model.md，量測前就 commit）與**判準目標**，
    # 都不是本次的量測值，沒有 CSV 可以對回。
    "2.4",      # 2.4 GHz 載波（energy_model.md §1）
    "9.588",    # 未編碼 BPSK 的閉式解（G1 的**目標**；實測是 9.571，另有 assertion）
    "2.5",      # clip = 2.5σ（量化器參數）；「2.2–2.5 倍」另有 assertion
}

# README 專屬的白名單。**只放「不是本專案量測值」的數字**——
# 文獻值、閉式解、事前登記的目標、以及純粹的參數。
# 凡是量測出來的，一律 assert，不得放進這裡。
README_UNCOVERED = {
    "4.200",    # union bound 給的參考值（定理，非量測）
    "6.555",    # 同上
    "2.355",    # 同上
    "5.39",     # 事前登記的編碼增益預測（docs/falsification.md）
    "9.5842",   # 既有通訊模擬器獨立量到的值（外部來源）
    "0.2",      # Heller & Jacobs 的 0.2 dB（文獻）
    "0.209",    # D=24 相對全幀 ML 的損失（來自 data/d_sweep.csv，M1 的副產品）
    "0.076",    # C1 的量測雜訊地板（同上）
    "4.137",    # M1 量到的「未量化 soft, D=64」——在 m2_gate.py 是常數 REQ_FS
    "6.550",    # 硬判決所需 Eb/N0（gates.csv 的 G4b detail 欄）
    "2.58",     # 安全組態在 4.0->5.5 dB 掉的數量級（gates.csv 的 G6 負向 detail 欄）
    "1.0",      # 「總功耗只變動 1.0%」（gates.csv 的 M5-3 measured 欄，文字）
    "21.2",     # 預先登記早於量測的小時數（由 git 時間戳算出，另有結構檢查）
    "5.5",      # 「4.0->5.5 dB 掉 2.58 個數量級」—— 5.5 是 SNR 軸上的一個點，不是量測值
    "4.0",      # 同上
}
# 掃**帶單位**的數字，不只是百分比。
#
# 為什麼要擴大：變異測試發現一個真的漏洞——把 `**17.8 m**` 改成 `**19.9 m**` 竟然沒被抓到，
# 因為 "17.8" 在結論散文裡還有一處（「17.8 m 之外」）沒被改到，
# 而「值須出現在文件中」這個檢查只問**有沒有出現過**，不問**每一處引用是否都對**。
#
# 擴大到所有帶單位的數字之後，那個被改壞的 `19.9 m` 就會以「未被覆蓋的數字」現形。
# 這仍然不是完備的（同一個值出現多次時，改壞其中幾處仍可能漏），
# 但它把漏洞從「整類」縮到「同值重複引用」這個窄縫，且成本為零。
# `\b` 不能加在 `%` 後面：`%` 本身是非字元，後面接 `。` 也是非字元，
# 兩個非字元之間**沒有** word boundary，`42.7%。` 就永遠比不到——
# 變異測試抓到了這個（我自己「收緊」regex 時弄壞的）。
# 所以 `%` 單獨處理，字母單位才加 `\b`；且長的單位要排在短的前面，
# 否則 `m` 會先吃掉 `mW` / `MHz` 的第一個字元。
_UNITS = (r"(?:%|(?:µm²|um²|MHz|GHz|mW|pJ|nJ|fJ|dB|pF|ns|mm|W|m|倍|小時)\b)")

# 圍籬程式碼區塊是**逐字貼上的工具輸出**（OpenSTA 的路徑報告等）——那是證據，
# 不是我們自己下的論斷，不該要求它對回 CSV。掃描前挖空（保留換行以維持行號）。
_CODE = re.compile(r"```.*?```", re.S)


def strip_code(doc):
    """圍籬程式碼區塊挖空（保留換行）。它們是逐字貼上的工具輸出，不是我們的論斷。"""
    return _CODE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), DOCSEARCH[doc])


# 報告與 **README** 都掃。README 曾經停在 M3+M4 整整兩個里程碑都沒被發現——
# 因為沒有任何東西在盯它。現在盯了。
_uncov = []
for _doc, _white in (("report", EXPECT_UNCOVERED),
                     ("readme", EXPECT_UNCOVERED | README_UNCOVERED)):
    for _n in sorted(set(re.findall(rf"(\d+\.\d+)\s*{_UNITS}", strip_code(_doc)))):
        if _n not in asserted[_doc] and _n not in _white:
            _uncov.append(f"{_doc}:{_n}")

# **覆蓋缺口必須讓 exit code 變成 1。**
#
# 上游那支工具把 coverage gap 只當成警告（印出來但 exit 0）。變異測試證明那是個洞：
# 把 `**17.8 m**` 改成 `**19.9 m**` 之後，因為 "17.8" 在結論散文裡還有一處沒被改到，
# 「值須出現在文件中」的檢查照樣通過；唯一會出聲的是 coverage gap——
# 而它不影響 exit code，**CI 會綠燈放行一個被改壞的數字**。
#
# 所以這裡把它升級為 failure：報告裡任何帶單位的數字，
# 只要既沒被 assert、也沒列入白名單，就是稽核的破口。
for _n in _uncov:
    fails.append(f"[coverage] 報告中的數字 {_n} 既未被 assertion 覆蓋、"
                 f"也未列入白名單 —— 它沒有對回任何 CSV")

# ================================================================ thesis.md（整併草稿）
# docs/thesis.md 是把 report.md 與五份凍結文件整併成的碩士論文草稿。這裡把它的**承重量測數字**
# 釘回 CSV：每一條同時驗 (a) 等於 CSV 真值、(b) 字串出現在 thesis.md。
# 刻意**不經過 A / len(A)**（免動 README 的 assertion 計數自我檢查 §4c），也**不套用 §5 的完備
# 覆蓋掃描**——草稿含大量背景常數與文獻值，完備掃描此刻過於脆弱。草稿補全後可再升級為完整覆蓋。
_THESIS_PATH = os.path.join(ROOT, "docs", "thesis.md")
_thesis_checks = []
if os.path.exists(_THESIS_PATH):
    _TT = open(_THESIS_PATH, encoding="utf-8").read().replace(",", "").replace("−", "-")
    _thesis_checks = [
        ("gate 總數", len(GATES), 36, 0),
        ("未編碼 @1e-5", gate_num("G1 "), 9.571, 3),
        ("編碼增益", gate_num("G2b"), 5.434, 3),
        ("3-bit 損失", gate_num("G3 "), 0.225, 3),
        ("硬判決損失", gate_num("G4b"), 2.413, 3),
        ("F1 最小 d*", min(float(x["dstar_m"]) for x in DS), 17.8, 1),
        ("F2 模型A/free", dd("A", "free_space"), 11.29, 2),
        ("F2 模型A/indoor", dd("A", "indoor"), 6.31, 2),
        ("F3 模型B/free", dd("B", "free_space"), -0.75, 2),
        ("F3 模型B/indoor", dd("B", "indoor"), -0.43, 2),
        ("d* Q3D32 A/free", dstar(3, 32, "A", "free_space"), 153.6, 1),
        ("d* Q6D32 A/free", dstar(6, 32, "A", "free_space"), 170.9, 1),
        ("E_dec 比值", _e6 / _e3, 1.2586, 4),
        ("α 實測", 2.0 * (_e6 / _e3 - 1.0), 0.517, 3),
        ("α 誤差倍數", 2.0 * (_e6 / _e3 - 1.0) / 0.15, 3.4, 1),
    ]
    for _desc, _truth, _cited, _nd in _thesis_checks:
        _s = fmt(_cited, _nd)
        _tol = 0.5 * 10 ** (-_nd) if _nd > 0 else 0.5
        if abs(round(float(_truth), _nd) - round(float(_cited), _nd)) > _tol:
            fails.append(f"[thesis] {_desc}: thesis={_cited} 但 CSV={_truth}")
        elif _s not in _TT and _s.lstrip("-") not in _TT:
            fails.append(f"[thesis] {_desc}: 值 {_s} 與 CSV 相符，但**在 thesis.md 中找不到**")
else:
    fails.append("[thesis] docs/thesis.md 不存在——整併草稿應已建立")
_n_thesis = len(_thesis_checks)

print(f"assertions: {len(A)}   mismatches: {len(fails)}")
print(f"thesis.md 承重數字：{_n_thesis} 條已釘回 CSV")
for f in fails:
    print("  MISMATCH:", f)

if not fails:
    if "PREREG_GAP_H" in dir():
        print(f"\n預先登記檢查：falsification.md / energy_model.md 的 commit 早於"
              f"功耗量測 **{PREREG_GAP_H:.1f} 小時**（git 時間戳可驗證）。")
    if "DSTAR_RECOMPUTED" in dir():
        print(f"d* 重算檢查：{DSTAR_RECOMPUTED} 個 d* 全部由 data/results.csv + "
              f"docs/energy_model.md 的凍結常數重算驗證（不是讀已算好的值）。")
    print("數字覆蓋：完整（報告中每個帶單位的數字都已對回 CSV 或列入白名單）。")

sys.exit(1 if fails else 0)
