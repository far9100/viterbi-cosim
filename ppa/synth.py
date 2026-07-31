"""synth.py — Sky130 合成（Yosys 0.64，在 ORFS 容器內）。

## 為什麼**不** flatten

功耗路徑需要階層才能做 `report_power -instances [get_cells u_acs]`，
而分區塊功耗是 M5 的救命稻草：

    計畫的風險 R1 —— survivor 記憶體（register exchange 的 64 × D 個 flop）支配面積，
    而它的活動量幾乎與 SNR 無關（每個 stage 都改寫全部 64 個暫存器，不管 SNR 多少）。
    後果是**總功耗對 SNR 的依賴可能只有幾個百分點，而不是一條曲線**——
    而規格書 §7 把那條曲線列為交付結果。

    唯一的救法是把功耗拆成 P_total / P_ACS / P_traceback，各自對 SNR 作圖，
    證明 SNR 依賴集中在 ACS。這比一條平坦的總曲線更有資訊量，而且誠實。

面積與 Fmax 走另一條路（扁平 + P&R），見 ppa/orfs/。
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.design as DESIGN  # noqa: E402
from scripts.gates import REPO  # noqa: E402

LIB = "/OpenROAD-flow-scripts/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"

# 單一來源：scripts/design.py
RTL = DESIGN.MODULES

# viterbi_top 底下的區塊（netlist 裡的實例名）
BLOCKS = ["u_ctrl", "u_bmu", "u_acs", "u_minpm", "u_tb"]

OUT = os.path.join(REPO, "ppa", "out", "synth")


# ---- clock gating（M9 / docs/lowpower_baseline.md 的 B1 態）----
#
# M5 的整條流程**沒有任何 clock gating**——只有 synth / dfflibmap / abc -liberty，
# 而 abc 只做技術映射。那條扇出 8683 個 sink 的 enable 網就是直接症狀。
# 由於 report.md §4 的負面結果是在這個未最佳化的設計上量到的，
# 「把與 SNR 無關的大分母縮小之後 null 還在不在」是必須回答的問題。
#
# Sky130 HD 的 ICG（integrated clock gating）cell：
#   sky130_fd_sc_hd__dlclkp_1   clock_gating_integrated_cell : "latch_posedge"
#     CLK  = clock_gate_clock_pin
#     GATE = clock_gate_enable_pin（active high）
#     GCLK = clock_gate_out_pin
# 由 liberty 實地查得（不是從文件抄的），area = 17.5168 µm²。
ICG_CELL = "sky130_fd_sc_hd__dlclkp_1"
ICG_PINS = "GATE:CLK:GCLK"

# 只 gate ≥ 64 個 flop 的群組：把控制 FSM（數十個 flop）留在 gating 之外。
# 64 = 一個 trellis stage 的狀態數，也正好把 traceback（64×D）、PM（64×W）、
# surv_r（64）納入，而把 bm_r（4×(Q+1)）與 ctrl 排除。
CG_MIN_NET = 64


def synth(Q, W, D, ninfo=1024, period_ps=10000, clock_gating=False,
          rtl_dir="/work/rtl", tag_suffix=""):
    """合成一組組態。回傳 (netlist 路徑, stat 解析結果)。

    clock_gating=False 為 B0（M5 的現況，數字必須逐位元組不變）；
    True 為 B1，插入 ICG。兩態的 RTL 源碼、激勵、SAIF→OpenSTA 路徑完全相同，
    只有這一個合成選項不同 —— 差異才能歸因於最佳化本身。

    rtl_dir / tag_suffix：讓「RTL 改寫是否擾動 B0」這個問題可以被**實測**回答，
    而不是用推理保證。改寫後的 RTL 先合成到另一個 tag，與現行 B0 netlist 逐一比對
    cell 組成與面積；只有證實不受擾動，才允許把改寫合併回 `rtl/`。
    """
    tag = f"Q{Q}_W{W}_D{D}" + ("_cg" if clock_gating else "") + tag_suffix
    os.makedirs(OUT, exist_ok=True)
    ys = os.path.join(OUT, f"syn_{tag}.ys")
    net = f"/work/ppa/out/synth/net_{tag}.v"
    stat = f"/work/ppa/out/synth/stat_{tag}.txt"
    # clockgate 必須在 dfflibmap **之前**跑：它要辨識的是通用的 $_DFFE_* cell，
    # dfflibmap 之後 FF 已經被映射成 liberty cell，pass 就認不出 enable 腳了。
    #
    # **已知陷阱（C2 抓到的）**：本 pass 從 FF 的 CE 腳推導 enable，而**同步 reset
    # 不在 CE 裡**（Yosys 把它折進 D 路徑）。於是 reset 拉高但 enable 為低時，
    # 時脈被關掉、reset 永遠進不去，設計卡在 X。症狀極隱蔽：TB 只在 out_valid 為 1
    # 時檢查 X，而 out_valid 自己就是 X ⇒ 回報「0 個輸出」而不是「X 錯誤」。
    # 因此要 clock gate 的 RTL 必須把 reset 寫進 enable 條件（`if (rst || en)`）。
    #
    # `-min_net_size` 把**小的暫存器群組排除在 gating 之外**。這不是效能微調，是正確性：
    # 控制 FSM（`rtl/ctrl.sv`，數十個 flop）的 enable 由它自己的狀態導出，
    # 一旦連它也被 gate，reset 就進不去，整個設計卡死。而它本來就小到 gate 了也省不了功耗。
    # 真正值得 gate 的是 traceback 的 64×D 與 PM 的 64×W 兩組暫存器庫。
    cg = (f"clockgate -min_net_size {CG_MIN_NET} -pos {ICG_CELL} {ICG_PINS}\n"
          if clock_gating else "")

    files = " \\\n  ".join(f"{rtl_dir}/{f}" for f in RTL)
    with open(ys, "w") as f:
        f.write(f"""\
# 由 ppa/synth.py 產生。Q={Q} W={W} D={D}
#
# -DSYNTHESIS：把 rtl/viterbi_top.sv 裡的 G6 影子（`ifndef SYNTHESIS）整段排除。
#              那是模擬用的哨兵，不是要出貨的邏輯。
read_verilog -sv -DSYNTHESIS -I{rtl_dir} \\
  {files}

chparam -set Q {Q} -set W {W} -set D {D} -set NINFO {ninfo} viterbi_top
hierarchy -check -top viterbi_top

# **不加 -flatten**：功耗要分區塊，必須保留階層
synth -top viterbi_top

{cg}dfflibmap -liberty {LIB}
abc        -liberty {LIB} -D {period_ps}

setundef -zero
opt_clean -purge

tee -o {stat} stat -liberty {LIB}
write_verilog -noattr {net}
""")

    p = subprocess.run(
        ["bash", os.path.join(REPO, "ppa", "orfs.sh"),
         f"yosys -q -s /work/ppa/out/synth/syn_{tag}.ys"],
        cwd=REPO, capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"Yosys 失敗 ({tag}):\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")

    return parse_stat(os.path.join(OUT, f"stat_{tag}.txt"), tag, Q, W, D)


# viterbi_top 底下每個模組的實例數。butterfly 有 32 個。
INSTANCES = {"bmu": 1, "ctrl": 1, "acs_array": 1, "acs_butterfly": 32,
             "minpm": 1, "traceback": 1}

# 區塊 -> 組成它的模組（用來算分區塊面積）
BLOCK_OF = {"bmu": "u_bmu", "ctrl": "u_ctrl",
            "acs_array": "u_acs", "acs_butterfly": "u_acs",
            "minpm": "u_minpm", "traceback": "u_tb"}


def _base_name(mangled):
    """Yosys 會把參數化的模組改名成 `$paramod$<hash>\\<name>` 或
    `$paramod\\<name>\\<param>=...`。把原始模組名還原出來。"""
    s = mangled.lstrip("\\")
    if not s.startswith("$paramod"):
        return s
    # $paramod$<hash>\name   或   $paramod\name\P=...
    m = re.search(r"\\([A-Za-z_][A-Za-z0-9_]*)", s)
    return m.group(1) if m else s


def parse_stat(path, tag, Q, W, D):
    """解析 Yosys 的階層式 stat。

    重點：`Chip area for module X` 是**該模組自己的 cell** 的面積，
    **不含**它實例化的子模組。所以 viterbi_top 自己是 0（它只是接線），
    真正的總數要看 `=== design hierarchy ===` 那一段的
    `Chip area for top module`。分區塊的面積則要自己乘上實例數。
    """
    with open(path) as f:
        txt = f.read()

    mods = {}
    total_area = 0.0
    total_cells = 0
    total_dff = 0

    # 兩個 regex 的坑（第一版都踩了）：
    #  1. 段落標題不能用 (\S+)：最後一段是 "=== design hierarchy ===",
    #     中間有空白，(\S+) 永遠比不到，於是總面積一直是 0。
    #  2. 模組名裡**有單引號**（$paramod\minpm\W=s32'0000...），
    #     所以 'Chip area for module ...' 的 '[^']+' 會在 s32' 那裡就停住。
    #     要用貪婪的 (.+) 一路吃到最後一個 ': 。
    for m in re.finditer(r"^=== (.+?) ===$(.*?)(?=^=== |\Z)", txt, re.S | re.M):
        raw = m.group(1).strip()
        body = m.group(2)

        # Yosys 的 stat 每一行是 "<數量> <面積> <cell 名>"（數量在**前面**）。
        # 第一版把 regex 寫成「cell 名後面接數字」，於是 DFF 數全是 0。
        def _cells(b):
            m2 = re.search(r"^\s*(\d+)\s+[\d.E+]+\s+cells\s*$", b, re.M)
            return int(m2.group(1)) if m2 else 0

        def _dff(b):
            # `e?df` —— **有 enable 的 FF 也是 FF**。
            #
            # 第一版寫 `__df\w+`，比不到 `sky130_fd_sc_hd__edfxtp_1`。
            # 在 B0（`rtl/`）上看不出來：Yosys 把它全部映成 dfxtp、edfxtp 是 0 個，
            # 所以 M5 已發表的 flop 數（2429）本來就是對的，改這條不會動到它。
            # 但 `rtl_lowpower/` 的 `if (rst || en)` 改寫讓 Yosys 推導出 enable-FF，
            # 於是 B0′ 的 2429 個 flop 只有 59 個被算到 —— **少算 97.6%**。
            # 而「clock gating 省下的是每個 flop 的回授 mux」這個結論，正是靠
            # edfxtp → dfxtp + ICG 的消長看出來的：漏掉 edfxtp 等於把唯一能佐證
            # 那個機制的統計量歸零，而且不會有任何錯誤訊息。
            return sum(int(x) for x in re.findall(
                r"^\s*(\d+)\s+[\d.E+]+\s+sky130_fd_sc_hd__e?df\w+", b, re.M))

        def _seq_area(b):
            m2 = re.search(r"sequential elements:\s*([\d.]+)", b)
            return float(m2.group(1)) if m2 else 0.0

        if raw.startswith("design"):       # "=== design hierarchy ==="
            a = re.search(r"Chip area for top module '(.+)':\s*([\d.]+)", body)
            if a:
                total_area = float(a.group(2))
            total_cells = _cells(body)
            total_dff = _dff(body)
            continue

        name = _base_name(raw)
        a = re.search(r"Chip area for module '(.+)':\s*([\d.]+)", body)
        if a and name in INSTANCES:
            n = INSTANCES[name]
            area_each = float(a.group(2))
            mods[name] = {
                "area_each_um2": area_each,
                "instances": n,
                "area_total_um2": area_each * n,
                "cells_each": _cells(body),
                "dff_each": _dff(body),
                "dff_total": _dff(body) * n,
                "seq_area_each_um2": _seq_area(body),
                "seq_area_total_um2": _seq_area(body) * n,
            }

    # 分區塊彙總
    blocks = {}
    for name, m in mods.items():
        b = BLOCK_OF[name]
        blocks.setdefault(b, {"area_um2": 0.0, "dff": 0, "seq_area_um2": 0.0})
        blocks[b]["area_um2"] += m["area_total_um2"]
        blocks[b]["dff"] += m["dff_total"]
        blocks[b]["seq_area_um2"] += m["seq_area_total_um2"]

    for b in blocks:
        blocks[b]["area_pct"] = (100.0 * blocks[b]["area_um2"] / total_area
                                 if total_area else 0.0)

    return {
        "tag": tag, "Q": Q, "W": W, "D": D,
        "total_area_um2": total_area,
        "total_cells": total_cells,
        "total_dff": total_dff,
        "modules": mods,
        "blocks": blocks,
    }


def main():
    # M2 選出的 winner（單一來源：scripts/design.py）。
    # 順序沿用 ORDER_SYNTH —— 改順序會改變合成 log 的順序。
    winners = [(Q, W, D) for Q, W, D, _clip
               in DESIGN.winners(DESIGN.ORDER_SYNTH)]

    rows = []
    for Q, W, D in winners:
        print(f"=== 合成 Q={Q} W={W} D={D}")
        sys.stdout.flush()
        r = synth(Q, W, D)
        rows.append(r)

        print(f"  總面積 {r['total_area_um2']:>10.0f} µm²   "
              f"{r['total_cells']:>6d} cells   {r['total_dff']:>5d} DFF")
        for b, m in sorted(r["blocks"].items(), key=lambda x: -x[1]["area_um2"]):
            print(f"    {b:10s} {m['area_um2']:>10.0f} µm²  "
                  f"{m['area_pct']:>5.1f}%  {m['dff']:>5d} DFF")
        print()

    with open(os.path.join(OUT, "synth.json"), "w") as f:
        json.dump(rows, f, indent=2)

    print("=== 風險 R1 的裁決：survivor 記憶體（register exchange）是否支配面積？")
    for r in rows:
        tb = r["blocks"].get("u_tb", {})
        mp = r["blocks"].get("u_minpm", {})
        print(f"  {r['tag']:14s} traceback {tb.get('area_pct', 0):>5.1f}% 的面積、"
              f"{100.0*tb.get('dff',0)/max(r['total_dff'],1):>5.1f}% 的 flop  |  "
              f"min-PM 樹 {mp.get('area_pct', 0):>5.1f}%")

    print(f"\n-> {OUT}/synth.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
