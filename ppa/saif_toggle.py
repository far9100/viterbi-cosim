"""saif_toggle.py — 從 SAIF 量出「SNR 依賴到底死在哪一級」。

## 為什麼有這個檔

規格書 §7 把「功耗對 SNR 的依賴曲線」列為交付結果，前提是
「低 SNR → ACS toggle 率高 → 功耗高」。**實測這個前提是錯的**：
總功耗在 1→5 dB 只變動 1.0%，而且方向相反、非單調（= 雜訊）。

分區塊也救不了它。所以正確的作法不是把一條平的曲線畫出來假裝有效應，
而是**量出它為什麼不存在**——把 null result 變成機制。

SAIF 剛好存了每條 net 的 TC（翻轉次數）與 T0/T1（高低態時間），
而這正是 switching power 的**輸入**：P_sw ∝ Σ C_i · TC_i · V²/2 · f。
所以直接讀 SAIF 就能沿著資料路徑追蹤「SNR 資訊」在哪一級被消滅：

    r（通道輸入） → bm（分支度量） → pm（路徑度量） → **surv（倖存者決策）** → re（暫存器交換）

## 已知的答案（planning 階段實測，這裡是把它變成可重生的交付物）

`surv_pk` 的翻轉率在 1/3/5 dB 分別是 0.4661 / 0.4667 / 0.4659（變動 0.17%），
duty ≈ 0.48。**倖存者決策在任何 SNR 下都是擲硬幣。**
register exchange 每個 stage 用這 64 個硬幣改寫全部 64 個暫存器
⇒ traceback（54–67% 的功耗）在結構上不可能依賴 SNR。

## 兩個必須注意的正規化細節

1. **翻轉密度 TC/n_cycles 是強度量（intensive）**，與跑幾個 frame 無關，所以
   不同 frame 數的 SAIF 可以直接比。（本專案曾經有一個 SAIF 檔名碰撞的 bug，
   3 dB 的 SAIF 是 2-frame 的——即使如此密度仍可比，因為
   cycles/stage 的比值完全相同：3306/3090 = 2204/2060 = 1.0699。已修。）
2. **Σ TC 是外延量（extensive）**，要拿來對比 switching power 必須除以 n_cycles。
   本檔會做這個對比當作**獨立的一致性檢查**：若 Σ(TC)/cycle 隨 SNR 的變化
   與 OpenSTA 報的 switching power 隨 SNR 的變化對不上，代表 SAIF→OpenSTA
   這條路上有東西壞了。
"""

import argparse
import collections
import csv
import glob
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.gates import DATA  # noqa: E402

CLK_NS = 10.0        # 100 MHz —— 與 ppa/power.py 一致

# SAIF 的 net 名稱是跳脫過的（`surv_pk\[3\]`）。還原後再分類。
_UNESC = re.compile(r"\\(.)")

_INST = re.compile(r"^(\s*)\(INSTANCE (\S+)")
_NAME = re.compile(r"^\s*\((\S+)\s*$")
_T012 = re.compile(r"^\s*\(T0 (\d+)\) \(T1 (\d+)\) \(TX (\d+)\)")
_TC = re.compile(r"^\s*\(TC (\d+)\)")
_DUR = re.compile(r"^\s*\(DURATION (\d+)\)")
_TS = re.compile(r"^\s*\(TIMESCALE (\d+) (\S+)\)")

_UNIT_PS = {"fs": 1e-3, "ps": 1.0, "ns": 1e3, "us": 1e6, "ms": 1e9, "s": 1e12}

# 語意分類：(scope 後綴, net 名稱前綴) -> 類別。順序有意義，先中者勝。
#
# 這條資料路徑就是解碼器本身：通道軟值 -> 分支度量 -> 路徑度量 -> 倖存者決策 -> 暫存器交換。
# 「SNR 的資訊」從左邊進來，我們要看它在哪一級變成雜訊。
# 注意 scope "" = dut 自己（頂層的 net / port）。不是 "dut"——scope 路徑是**相對 dut** 的。
CLASSES = [
    ("in_r",      "",         ("r0", "r1"),                 "通道軟值 r（解碼器的輸入）"),
    ("bm",        "u_bmu",    ("bm_pk", "m0_", "m1_"),      "分支度量 bm[4]"),
    ("pm",        "u_acs",    ("pm_pk",),                   "路徑度量 pm[64]（累加器）"),
    ("surv",      "u_acs",    ("surv_pk",),                 "倖存者決策（暫存後）"),
    ("surv_comb", "u_acs",    ("surv_comb_pk",),            "倖存者決策（組合，含 glitch）"),
    ("re",        "u_tb",     ("re", "re_next", "re_msb"),  "register-exchange 暫存器"),
    ("best",      "u_minpm",  ("best",),                    "min-PM 的 argmin 輸出"),
]

# 每個區塊的「所有 net」（含 ABC 產生的內部 net _1234_）——這才是 switching power 的來源
BLOCK_SCOPES = ["u_acs", "u_tb", "u_minpm", "u_bmu", "u_ctrl"]


def _prefix(name):
    """把 `surv_pk[3]` / `re[12][7]` 收斂成前綴 `surv_pk` / `re`。"""
    i = name.find("[")
    return name if i < 0 else name[:i]


def parse(path):
    """單次掃描 SAIF。回傳 (nets, n_cycles)。

    nets: list of (scope_path, netname, t0, t1, tx, tc)
    scope_path 是相對 `dut` 的路徑，例如 "" (dut 本身)、"u_acs"、"u_acs/g_bfly[0].u_b"。
    """
    nets = []
    stack = []
    scope = None
    name = None
    t012 = None
    dur = None
    ts_ps = 1.0

    # 入庫的是 .saif.gz（gzip 有 27.6 倍：466 MB -> 18 MB）。兩種都吃，
    # 這樣「git clone 後直接重算」與「剛跑完模擬」兩條路都通。
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as f:
        for line in f:
            m = _INST.match(line)
            if m:
                d = len(m.group(1)) // 2
                stack = stack[:d - 1] + [m.group(2)]
                # 只保留 dut 以下的相對路徑
                scope = "/".join(stack[2:]) if len(stack) >= 2 else None
                name = None
                continue

            m = _TC.match(line)
            if m and name is not None and t012 is not None and scope is not None:
                nets.append((scope, name) + t012 + (int(m.group(1)),))
                name = None
                t012 = None
                continue

            m = _T012.match(line)
            if m and name is not None:
                t012 = tuple(int(x) for x in m.groups())
                continue

            if dur is None:
                m = _DUR.match(line)
                if m:
                    dur = int(m.group(1))
                    continue
                m = _TS.match(line)
                if m:
                    ts_ps = int(m.group(1)) * _UNIT_PS[m.group(2)]
                    continue

            m = _NAME.match(line)
            if m and scope is not None:
                tok = m.group(1)
                if tok not in ("NET", "INSTANCE"):
                    name = _UNESC.sub(r"\1", tok)
                    t012 = None

    n_cycles = (dur * ts_ps) / (CLK_NS * 1000.0)
    return nets, n_cycles


def classify(scope, name):
    pre = _prefix(name)
    for cls, sc, prefixes, _ in CLASSES:
        if scope == sc and pre in prefixes:
            return cls
    return None


def summarize(path):
    nets, ncyc = parse(path)

    agg = collections.defaultdict(lambda: [0, 0.0, 0.0])   # n, sum_tc, sum_duty
    blk = collections.defaultdict(lambda: [0, 0])          # n, sum_tc
    seen_prefix = collections.Counter()

    for scope, name, t0, t1, tx, tc in nets:
        tot = t0 + t1 + tx
        duty = (t1 / tot) if tot else 0.0

        cls = classify(scope, name)
        if cls:
            a = agg[cls]
            a[0] += 1
            a[1] += tc
            a[2] += duty
            seen_prefix[(cls, _prefix(name))] += 1

        # 區塊層級：該區塊底下的所有 net（含子 scope 與 ABC 內部 net）
        top = scope.split("/")[0] if scope else "dut"
        if top in BLOCK_SCOPES:
            b = blk[top]
            b[0] += 1
            b[1] += tc

    out = {"n_cycles": ncyc, "classes": {}, "blocks": {}}
    for cls, sc, prefixes, desc in CLASSES:
        if cls in agg:
            n, stc, sduty = agg[cls]
            out["classes"][cls] = {
                "n_nets": n,
                "tc_per_cycle": stc / n / ncyc,   # 每條 net 每 cycle 的平均翻轉次數
                "duty": sduty / n,
                "desc": desc,
            }
    for b, (n, stc) in blk.items():
        out["blocks"][b] = {"n_nets": n, "sum_tc_per_cycle": stc / ncyc}
    out["_prefixes"] = {f"{c}:{p}": n for (c, p), n in seen_prefix.items()}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saif-dir", default=os.path.join(DATA, "saif"))
    ap.add_argument("--out", default=os.path.join(DATA, "results_m5_toggle.csv"))
    args = ap.parse_args()

    # 只看主掃描（3 frame 的點）——那是「功耗 vs SNR」的交付點。
    # 未壓縮的優先（剛跑完模擬）；沒有就吃入庫的 .gz（git clone 後的重算路徑）。
    files = sorted(glob.glob(os.path.join(args.saif_dir, "act_*_f3.saif")))
    if not files:
        files = sorted(glob.glob(os.path.join(args.saif_dir, "act_*_f3.saif.gz")))
    if not files:
        print(f"找不到 SAIF：{args.saif_dir}/act_*_f3.saif[.gz]", file=sys.stderr)
        return 1

    # OpenSTA 報的 switching power，用來做獨立的一致性檢查
    with open(os.path.join(DATA, "power.json")) as f:
        pw = {(p["tag"], p["snr_db"]): p for p in json.load(f)["points"]}

    rows = []
    res = {}
    for path in files:
        m = re.match(r"act_(Q\d+_W\d+_D\d+)_snr([\d.]+)_f(\d+)\.saif(?:\.gz)?$",
                     os.path.basename(path))
        tag, snr, frames = m.group(1), float(m.group(2)), int(m.group(3))
        s = summarize(path)
        res[(tag, snr)] = s
        print(f"  解析 {os.path.basename(path):34s} "
              f"{s['n_cycles']:7.0f} cycles", flush=True)

        for cls, d in s["classes"].items():
            rows.append({
                "tag": tag, "snr_db": snr, "frames": frames,
                "n_cycles": round(s["n_cycles"], 1),
                "signal": cls, "n_nets": d["n_nets"],
                "tc_per_cycle": round(d["tc_per_cycle"], 6),
                "duty": round(d["duty"], 6),
                "desc": d["desc"],
            })

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ---------------- 報告 ----------------
    sweep = sorted([k for k in res if k[0] == "Q4_W10_D64"], key=lambda k: k[1])

    print("\n=== 資料路徑上的翻轉密度（每條 net 每 cycle 的翻轉次數）"
          "—— Q=4 W=10 D=64")
    order = [c[0] for c in CLASSES]
    hdr = "".join(f"{c:>12}" for c in order)
    print(f"{'SNR':>5}{hdr}")
    for k in sweep:
        cs = res[k]["classes"]
        line = "".join(f"{cs[c]['tc_per_cycle']:>12.4f}" if c in cs else f"{'—':>12}"
                       for c in order)
        print(f"{k[1]:>5.0f}{line}")
    print(f"{'變動%':>5}", end="")
    for c in order:
        v = [res[k]["classes"][c]["tc_per_cycle"] for k in sweep
             if c in res[k]["classes"]]
        print(f"{100*(max(v)-min(v))/max(v):>12.2f}" if v else f"{'—':>12}", end="")
    print()

    print("\n=== duty（訊號為高的時間比例；0.5 = 最大熵 = 擲硬幣）")
    print(f"{'SNR':>5}{hdr}")
    for k in sweep:
        cs = res[k]["classes"]
        line = "".join(f"{cs[c]['duty']:>12.4f}" if c in cs else f"{'—':>12}"
                       for c in order)
        print(f"{k[1]:>5.0f}{line}")

    # ---- 跨層檢查：numpy golden 的預測 vs gate-level SAIF 的實測 ----
    # golden 算的是「每個 **stage**」的翻轉率；SAIF 算的是「每個 **cycle**」。
    # 一個 frame 有 T = NINFO + m 個 stage，但要跑 (T + flush) 個 cycle，
    # 所以兩者差一個 stages/cycles 的比例。這個比例直接從 SAIF 的 DURATION 與快取的
    # n_stages 算出來，不是猜的。
    mech = os.path.join(DATA, "results_m5_mechanism.csv")
    if os.path.exists(mech):
        with open(mech) as f:
            gm = {float(r["snr_db"]): r for r in csv.DictReader(f)
                  if r["case"] == "agc"}
        print("\n=== 跨層檢查：numpy golden（演算法）vs Sky130 gate-level SAIF（硬體）")
        print("    兩條路徑**完全獨立**。若吻合，代表機制在演算法裡，不在 RTL 裡。")
        print(f"{'SNR':>5} {'golden/stage':>13} {'stage/cycle':>12} "
              f"{'預測/cycle':>11} {'SAIF 實測':>10} {'差異':>8}")
        for k in sweep:
            g = gm.get(k[1])
            if not g:
                continue
            p = pw[("Q4_W10_D64", k[1])]
            ratio = p["n_stages"] / res[k]["n_cycles"]
            pred = float(g["tog_surv"]) * ratio
            meas = res[k]["classes"]["surv"]["tc_per_cycle"]
            print(f"{k[1]:>5.0f} {float(g['tog_surv']):>13.4f} {ratio:>12.4f} "
                  f"{pred:>11.4f} {meas:>10.4f} {100*(meas-pred)/pred:>7.2f}%")

    print("\n=== 一致性檢查：Σ TC/cycle（SAIF）vs switching power（OpenSTA）")
    print("    兩者是**獨立**算出來的。若跟不上，代表 SAIF→OpenSTA 這條路壞了。")
    print(f"{'SNR':>5}  {'區塊':>8} {'ΣTC/cyc':>10} {'相對1dB':>9}  "
          f"{'P_sw (mW)':>10} {'相對1dB':>9}")
    for b in ["u_acs", "u_tb", "u_minpm"]:
        base_tc = res[sweep[0]]["blocks"][b]["sum_tc_per_cycle"]
        base_sw = pw[("Q4_W10_D64", sweep[0][1])].get(f"p_{b}_sw_w", 0)
        for k in sweep:
            tc = res[k]["blocks"][b]["sum_tc_per_cycle"]
            sw = pw[("Q4_W10_D64", k[1])].get(f"p_{b}_sw_w", 0)
            print(f"{k[1]:>5.0f}  {b:>8} {tc:>10.1f} {100*tc/base_tc:>8.2f}%  "
                  f"{sw*1e3:>10.4f} {100*sw/base_sw:>8.2f}%")
        print()

    print(f"-> {args.out}（{len(rows)} 列）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
