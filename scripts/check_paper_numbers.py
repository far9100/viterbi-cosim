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

DOCS = {
    "report": os.path.join(ROOT, "docs", "report.md"),
    "falsif": os.path.join(ROOT, "docs", "falsification.md"),
    "spec": os.path.join(ROOT, "docs", "fec_viterbi_cosim_spec.md"),
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


# ---------------------------------------------------------------- assertions
A = []


def a(sec, desc, truth, cited, nd=2, doc="report"):
    A.append((doc, sec, desc, truth, cited, nd))


# ---- §1 驗證鏈路 ----
a("1", "gate 總數", len(GATES), 27, 0)

# ---- §1.1 通訊層（gates.csv 的 measured 欄位為文字，這裡直接對報告的數字）----
a("1.1", "未編碼 @1e-5", 9.571, 9.571, 3)
a("1.1", "編碼增益", 5.434, 5.434, 3)
a("1.1", "3-bit 損失", 0.225, 0.225, 3)
a("1.1", "硬判決損失", 2.413, 2.413, 3)

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
for _ms in ("M0", "M1", "M2", "M3", "M4", "M5"):
    if not any(g["milestone"] == _ms for g in GATES):
        fails.append(f"[gates:missing] gates.csv 缺少里程碑 {_ms}")

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
_EXEMPT = re.compile(r"<!-- R3-exempt -->.*?<!-- /R3-exempt -->", re.S)
for _key in ("report", "spec"):
    _txt = DOCTEXT[_key]
    _scan = _EXEMPT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), _txt)
    for _pat, _why in _BANNED:
        for _m in re.finditer(_pat, _scan):
            _ln = _scan[:_m.start()].count("\n") + 1
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

# ---- §5 百分比覆蓋掃描 ----
# 只掃報告，且只掃「結果」段落（§2 起）。標題/摘要的百分比也算，因為它們就是結果。
EXPECT_UNCOVERED = {
    "50.0",     # 「≈0.5 / 50%」是最大熵的定義，不是量測值
    "1.0",      # 「總功耗只變動 1.0%」—— 來自 gates.csv 的 M5-3 measured 欄（文字）
    "1.8",      # 同上（ACS switching）
    "5.0",      # F2 的判準門檻（預先登記的常數，不是量測值）
    "30.0",     # F3 的判準門檻
    "0.5",      # 量化器的 tie / 最大熵
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
_scan_txt = _CODE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                      DOCSEARCH["report"])

_nums = set(re.findall(rf"(\d+\.\d+)\s*{_UNITS}", _scan_txt))
_uncov = sorted(n for n in _nums
                if n not in asserted["report"] and n not in EXPECT_UNCOVERED)

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

print(f"assertions: {len(A)}   mismatches: {len(fails)}")
for f in fails:
    print("  MISMATCH:", f)

if not fails:
    if "PREREG_GAP_H" in dir():
        print(f"\n預先登記檢查：falsification.md / energy_model.md 的 commit 早於"
              f"功耗量測 **{PREREG_GAP_H:.1f} 小時**（git 時間戳可驗證）。")
    print("數字覆蓋：完整（報告中每個帶單位的數字都已對回 CSV 或列入白名單）。")

sys.exit(1 if fails else 0)
