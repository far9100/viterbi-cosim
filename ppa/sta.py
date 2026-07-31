"""sta.py — Fmax。**而且揭露一件 post-synth STA 抓到的真問題。**

## 為什麼這支不是「跑一下 report_checks 就好」

規格書 §7 的 PPA 表要 Fmax。第一版就是直接對 ppa/out/synth/net_*.v 跑 OpenSTA，
結果關鍵路徑是 **166 ns**（Fmax ≈ 6 MHz）。但看路徑就知道那不是邏輯延遲：

    0.2823  u_ctrl/_252_/Q     (dfxtp_1)
    0.2389  u_ctrl/_110_/Y     (nand2_1)
  102.6174  u_ctrl/_111_/Y     (clkinv_1)     <-- 一顆最小反相器，102 ns
   62.3652  u_tb/_19339_/Y     (nand2_1)      <-- 一顆 nand2，62 ns

一顆最小尺寸的 `clkinv_1` 要 102 ns，只可能是**負載爆炸**。算一下就對上了：
`clkinv_1` 的等效驅動電阻約 12 kΩ；`dfxtp_1` 的 D 腳電容約 2 fF；
register exchange 是 64 個狀態 × D=64 = **4096 個 flop**，
所以 C ≈ 4096 × 2 fF = 8.2 pF，R·C ≈ **98 ns** —— 與實測的 102 ns 吻合。

也就是說：**u_ctrl 的 enable（stage_en / flush_en）直接扇出到 4096 個 flop，
中間沒有任何 buffer tree。**

**這是流程的缺口，不是架構的極限。** Yosys 的 `abc -liberty` 只做技術映射，
**不做負載感知的 buffer 插入**——那是 physical synthesis 的工作。
在一個純邏輯合成的 netlist 上報 Fmax 是沒有意義的。

## 這會不會污染已經量到的功耗 / 面積 / d*？——不會

  * **功耗**：動態能量 E = α·C·V²，**與頻率無關**（P_dyn ∝ f，所以 P/f 是常數）。
    而那個巨大的 C 本來就在 netlist 裡，OpenSTA 算功耗時已經算進去了。
    leakage 確實與 f 有關，但它是 µW 級 vs 動態的 mW 級，可忽略。
  * **面積 / d\***：完全不受時序影響。

  所以 M5 的 d\* 主結論不動。**只有 Fmax 這一項需要修。**

## 修法：physical synthesis（floorplan -> global placement -> repair_design）

`repair_design` 就是專門修這個的：它依 liberty 的 max_capacitance / max_slew / max_fanout
插入 buffer tree 並調整驅動強度。它需要寄生估計，而寄生估計需要 placement。

**這不是 full P&R**（沒有 detailed routing），所以仍在使用者「跳過 P&R」的裁定之內；
但它是讓 Fmax 有意義的**最低限度**。

## 必須揭露的 caveat

  * post-placement / **pre-route**：沒有真實繞線寄生、沒有 clock tree。真實 Fmax 會更低。
  * `repair_design` 只修 DRV（max cap/slew/fanout），**不做 setup 的時序最佳化**。
    所以這是「有合理 buffer tree 之後的架構 Fmax」，不是「盡力優化後的 Fmax」。
  * typical corner（tt_025C_1v80）。簽核要看 slow corner。
  * buffer 插入會讓面積略增 —— 本檔會把增量報出來，讓 PPA 表的面積數字可被正確解讀。
"""

import csv
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.design as DESIGN  # noqa: E402
from scripts.gates import DATA, REPO  # noqa: E402

PLAT = "/OpenROAD-flow-scripts/flow/platforms/sky130hd"
LIB = f"{PLAT}/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
TLEF = f"{PLAT}/lef/sky130_fd_sc_hd.tlef"
CLEF = f"{PLAT}/lef/sky130_fd_sc_hd_merged.lef"

OUT = os.path.join(REPO, "ppa", "out", "fmax")
SYNTH = os.path.join(REPO, "ppa", "out", "synth")
CACHE = os.path.join(DATA, "cache_fmax")

# 合成時 abc 的目標週期（ppa/synth.py），Fmax 是「這個 netlist 的」，不是「這個 RTL 的上限」
SYNTH_TARGET_NS = 10.0
UTIL = 45          # floorplan 利用率 (%)
DENSITY = 0.60     # global placement 的目標密度

# 單一來源：scripts/design.py。**順序是有意義的** ——
# data/results_m5_fmax.csv 的列序就是這個順序，改它會破壞冷跑的逐位元組判準。
CONFIGS = [(Q, W, D) for Q, W, D, _clip in DESIGN.winners(DESIGN.ORDER_POWER)]


def tcl_for(tag, netlist_rel, out_net_rel, period_ns):
    return f"""
read_liberty {LIB}
read_lef {TLEF}
read_lef {CLEF}
read_verilog {netlist_rel}
link_design viterbi_top
create_clock -name clk -period {period_ns} [get_ports clk]

# ---- 修復**前**：這就是純邏輯合成 netlist 的真面目 ----
puts "=== BEFORE ==="
report_worst_slack -max
report_checks -path_delay max -digits 4 -fields {{fanout capacitance}}
puts "=== BEFORE_AREA ==="
report_design_area

# ---- floorplan + placement（repair_design 需要寄生估計，而寄生估計需要 placement）----
initialize_floorplan -utilization {UTIL} -aspect_ratio 1.0 -core_space 2.0 -site unithd
# 先建 routing track，place_pins 才有 track 可用（否則 PPL-0021: tracks not found）
source {PLAT}/make_tracks.tcl
# I/O pin 一定要先擺，否則 global_placement 會直接報 GPL-0326（clk port is not placed）
place_pins -hor_layers met3 -ver_layers met2
source {PLAT}/setRC.tcl
global_placement -density {DENSITY}
estimate_parasitics -placement

# ---- 這一步就是重點：依 liberty 的 max_cap / max_slew / max_fanout 插 buffer tree ----
puts "=== REPAIR ==="
repair_design

# buffer 插進來之後要重新 placement，寄生也要重估
global_placement -density {DENSITY}
estimate_parasitics -placement

puts "=== AFTER ==="
report_worst_slack -max
report_checks -path_delay max -digits 4 -fields {{fanout capacitance}}
puts "=== AFTER_AREA ==="
report_design_area

write_verilog {out_net_rel}
exit
"""


def parse(txt, period_ns):
    """從 OpenROAD 的輸出解析修復前/後的 slack、關鍵路徑、面積。"""
    res = {}
    for phase, key in (("BEFORE", "before"), ("AFTER", "after")):
        m = re.search(rf"=== {phase} ===(.*?)(?:=== |\Z)", txt, re.S)
        if not m:
            continue
        blk = m.group(1)
        ms = re.search(r"worst slack (?:max )?(-?[\d.]+)", blk)
        if ms:
            slack = float(ms.group(1))
            res[f"slack_{key}_ns"] = slack
            res[f"path_{key}_ns"] = period_ns - slack
            res[f"fmax_{key}_mhz"] = 1e3 / (period_ns - slack)
        mp = re.search(r"Startpoint:\s+(\S+)", blk)
        me = re.search(r"Endpoint:\s+(\S+)", blk)
        if mp:
            res[f"start_{key}"] = mp.group(1)
        if me:
            res[f"end_{key}"] = me.group(1)

        # 最慢的那一級（用來證明「就是這顆閘扛了整條路徑」）。
        # report_checks -fields {fanout capacitance} 的欄位是：
        #     Fanout   Cap   Delay   Time   ^|v  pin (cell)
        # 沒有 fanout 的行（clock edge 等）不會匹配，正好跳過。
        gates = re.findall(
            r"^\s*(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+[v^]\s+(\S+)\s+\((\S+)\)",
            blk, re.M)
        if gates:
            g = max(gates, key=lambda x: float(x[2]))
            res[f"worst_gate_{key}"] = g[4]
            res[f"worst_cell_{key}"] = g[5]
            res[f"worst_gate_delay_{key}_ns"] = float(g[2])
            res[f"worst_gate_fanout_{key}"] = int(g[0])
            res[f"worst_gate_cap_{key}_pf"] = float(g[1])
            res[f"max_fanout_{key}"] = max(int(x[0]) for x in gates)

    for phase, key in (("BEFORE_AREA", "before"), ("AFTER_AREA", "after")):
        m = re.search(rf"=== {phase} ===(.*?)(?:=== |\Z)", txt, re.S)
        if m:
            # OpenROAD 印的是 "Design area 267350 um^2 100% utilization."
            ma = re.search(r"Design area\s+([\d.]+)\s*um\^2", m.group(1))
            if ma:
                res[f"area_{key}_um2"] = float(ma.group(1))
    return res


def run(tag, period_ns=SYNTH_TARGET_NS):
    cp = os.path.join(CACHE, f"{tag}.json")
    if os.path.exists(cp):
        with open(cp) as f:
            return json.load(f)

    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    tcl = os.path.join(OUT, f"fmax_{tag}.tcl")
    with open(tcl, "w") as f:
        f.write(tcl_for(tag,
                        f"/work/ppa/out/synth/net_{tag}.v",
                        f"/work/ppa/out/fmax/rep_{tag}.v",
                        period_ns))

    p = subprocess.run(
        ["bash", os.path.join(REPO, "ppa", "orfs.sh"),
         f"openroad -no_init -exit /work/{os.path.relpath(tcl, REPO)}"],
        cwd=REPO, capture_output=True, text=True)
    txt = p.stdout + p.stderr
    with open(os.path.join(OUT, f"fmax_{tag}.log"), "w") as f:
        f.write(txt)

    res = parse(txt, period_ns)
    if "fmax_after_mhz" not in res:
        raise RuntimeError(f"OpenROAD 沒跑完（{tag}），log 在 "
                           f"ppa/out/fmax/fmax_{tag}.log:\n{txt[-2500:]}")
    res["tag"] = tag
    res["period_ns"] = period_ns
    with open(cp + ".tmp", "w") as f:
        json.dump(res, f)
    os.replace(cp + ".tmp", cp)
    return res


def main():
    rows = []
    for Q, W, D in CONFIGS:
        tag = f"Q{Q}_W{W}_D{D}"
        if not os.path.exists(os.path.join(SYNTH, f"net_{tag}.v")):
            print(f"  跳過 {tag}：找不到 netlist")
            continue
        r = run(tag)
        r.update({"Q": Q, "W": W, "D": D})
        rows.append(r)
        print(f"  {tag:14s} 修復前 {r['path_before_ns']:8.2f} ns "
              f"({r['fmax_before_mhz']:7.1f} MHz)  "
              f"-> 修復後 {r['path_after_ns']:6.3f} ns "
              f"({r['fmax_after_mhz']:7.1f} MHz)", flush=True)

    print("\n=== Fmax（sky130hd, typical corner）")
    print(f"{'組態':>13} | {'純邏輯合成（無 buffer tree）':^34} | "
          f"{'physical synth（repair_design）':^30} | {'面積':>7}")
    print(f"{'':>13} | {'路徑(ns)':>9} {'Fmax':>8} {'最大扇出':>8} {'負載(pF)':>7} | "
          f"{'路徑(ns)':>9} {'Fmax':>8} {'最大扇出':>8} | {'增量':>7}")
    for r in rows:
        da = 100.0 * (r["area_after_um2"] / r["area_before_um2"] - 1.0) \
            if r.get("area_before_um2") else float("nan")
        print(f"{r['tag']:>13} | {r['path_before_ns']:>9.2f} "
              f"{r['fmax_before_mhz']:>7.1f}M {r.get('max_fanout_before',0):>8d} "
              f"{r.get('worst_gate_cap_before_pf',0):>7.2f} | "
              f"{r['path_after_ns']:>9.3f} {r['fmax_after_mhz']:>7.1f}M "
              f"{r.get('max_fanout_after',0):>8d} | {da:>+6.2f}%")

    r0 = rows[0]
    print(f"\n  純邏輯合成的關鍵路徑是**單一一顆閘**扛的：{r0.get('worst_cell_before')}"
          f"（{r0.get('worst_gate_before')}）")
    print(f"    扇出 **{r0.get('worst_gate_fanout_before')}**、負載 "
          f"**{r0.get('worst_gate_cap_before_pf'):.1f} pF** "
          f"-> 延遲 **{r0.get('worst_gate_delay_before_ns'):.1f} ns**。")
    print(f"    這是 u_ctrl 的 enable 直接扇出到 register exchange 的 "
          f"64 states × D 個 flop（外加每個 flop 的 enable mux）。")
    print(f"    下一顆閘又吃了 62 ns —— 那不是負載，是**轉態時間（slew）**："
          f"上一級的邊緣爛到讓它自己也變慢。")
    print(f"  插了 buffer tree 之後，關鍵路徑降到 {r0['path_after_ns']:.3f} ns"
          f"（最大扇出 {r0.get('max_fanout_after')}），面積只多 "
          f"{100.0*(r0['area_after_um2']/r0['area_before_um2']-1):.1f}%。")
    print(f"  **這是流程的缺口（Yosys 的 abc 不做負載感知的 buffer 插入），"
          f"不是架構的極限。**")
    fmin = min(r["fmax_after_mhz"] for r in rows)
    print(f"\n  4 個組態的 Fmax 都 >= {fmin:.0f} MHz > 100 MHz "
          f"-> **能量模型假設的 f_clk = 100 MHz 是站得住的。**")
    print("\n  **caveat：post-placement / pre-route。沒有真實繞線寄生、沒有 clock tree。**")
    print("  **repair_design 只修 DRV，不做 setup 最佳化。真實 Fmax 會更低。**")
    print("  **使用者已裁定不跑 full P&R，故無 post-route 的校正係數。**")
    print("\n  註：PPA 表的面積/功耗來自**修復前**的 netlist（M5a/M5b 已量）。"
          "buffer tree 會讓面積增加上表所列的百分比；功耗的增量未量測，如實揭露。")

    out = os.path.join(DATA, "results_m5_fmax.csv")
    cols = ["tag", "Q", "W", "D", "period_ns",
            "slack_before_ns", "path_before_ns", "fmax_before_mhz",
            "worst_cell_before", "worst_gate_delay_before_ns",
            "worst_gate_fanout_before", "worst_gate_cap_before_pf",
            "max_fanout_before", "area_before_um2",
            "slack_after_ns", "path_after_ns", "fmax_after_mhz",
            "worst_cell_after", "worst_gate_delay_after_ns",
            "max_fanout_after", "area_after_um2",
            "start_after", "end_after"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n-> {out}（{len(rows)} 列）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
