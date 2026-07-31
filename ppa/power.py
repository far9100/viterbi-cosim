"""power.py — gate-level 功耗（真實 AWGN 資料驅動的 switching activity）。

規格書 §7 的硬性要求：**功耗不得用預設 toggle-rate 猜測**。

流程（M0 已用一個 8-bit counter 把整條路打通，annotation 100%）：

    Yosys（階層式，不 flatten）      -> netlist
    Icarus + sky130 behavioral model -> gate-level VCD（真實 AWGN 激勵驅動）
    ppa/vcd2saif.py（FIFO 串流）     -> SAIF（VCD 永不落地）
    OpenSTA read_saif -scope         -> report_power（總體 + 分區塊）

## 為什麼一定要分區塊

風險 R1：register exchange 的 traceback 佔了 68–84% 的 flip-flop，而它的活動量
幾乎與 SNR 無關（每個 stage 都改寫全部 64 個暫存器，不管 SNR 多少）。
所以**總功耗對 SNR 的依賴可能只有幾個百分點**——而規格書 §7 把那條曲線列為交付結果。

唯一的救法是把功耗拆成 P_total / P_ACS / P_traceback / P_minpm，各自對 SNR 作圖，
證明 SNR 依賴集中在 ACS。這比一條平坦的總曲線更有資訊量，而且誠實。

## VCD 為什麼不能落地

gate-level VCD 是 30–180 KB/cycle（34k 個 cell，每條 ABC-mapped net 都有 glitch）。
10k cycles 就是 GB 級，× 多個 (組態 × SNR) 點根本放不下。
SAIF 是 O(#nets) 而非 O(#nets × cycles)，每點幾 MB，可入庫當證據。
"""

import os
import re
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate  # noqa: E402
from golden.quantizer import quantize, sigma_from_ebn0  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from golden.viterbi_fx import decode_fx  # noqa: E402
from scripts.gates import DATA, REPO  # noqa: E402

LIB = "/OpenROAD-flow-scripts/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
MODELS = os.path.join(REPO, "ppa", "models", "sky130_fd_sc_hd")
OUT = os.path.join(REPO, "ppa", "out", "power")
SAIF_DIR = os.path.join(DATA, "saif")

# 每個 SNR 點跑幾個 frame。10 個 frame ≈ 10,300 個 stage —— 對 toggle 率的收斂
# 已經綽綽有餘（大數法則作用在 ~10^4 個獨立的 trellis stage 上），
# 而且 VCD 的體積還撐得住。收斂性由 convergence() 實測證明，不是假設。
FRAMES = 10
NINFO = 1024
CLK_NS = 10.0        # 100 MHz
BLOCKS = ["u_acs", "u_tb", "u_minpm", "u_bmu", "u_ctrl"]


def make_stimulus(Q, W, D, clip, snr, outdir, seed=20260714):
    """真實 AWGN 通道資料驅動的激勵（規格書 §7 的硬性要求）。"""
    os.makedirs(outdir, exist_ok=True)
    t = viterbi_trellis()
    T = NINFO + t.m
    sigma = sigma_from_ebn0(snr, code_rate(NINFO, t.m))
    rng = np.random.default_rng([seed, Q, W, D, int(snr * 10)])

    info = rng.integers(0, 2, size=(FRAMES, NINFO), dtype=np.uint8)
    cw = t.encode(info)
    x = 1.0 - 2.0 * cw.astype(np.float64)
    rx = x + rng.normal(0.0, sigma, size=x.shape)
    rq = quantize(rx, sigma, Q, clip)
    dec = decode_fx(rq, t, Q, W, D, NINFO, mode="window",
                    check_g6=False, keep_history=False)["dec"]

    sp = os.path.join(outdir, "stim.hex")
    dp = os.path.join(outdir, "dec.hex")
    with open(sp, "w") as f:
        for b in range(FRAMES):
            for tt in range(T):
                f.write(f"{rq[b, tt, 0]:x} {rq[b, tt, 1]:x}\n")
    with open(dp, "w") as f:
        for b in range(FRAMES):
            for i in range(NINFO):
                f.write(f"{int(dec[b, i])}\n")
    return sp, dp, T


def build_gl(tag, netlist, Q, W, D, ninfo=NINFO):
    """gate-level 模擬的編譯：netlist + 用到的 sky130 cell 行為模型 + 檔案驅動 TB。

    **一定要把 TB 的參數用 -P 覆寫掉。** netlist 的參數已經被烘焙進去了（沒有參數），
    但 TB 自己還有 Q/W/D/NINFO —— 它們決定 T = NINFO + 6、驅動幾個 stage、
    比對幾個位元。忘了覆寫的話 TB 會用預設值（D=32, NINFO=256）去驅動一個
    D=64, NINFO=1024 的 netlist，然後噴出一堆看起來像 RTL bug 的 C2 mismatch。
    （第一版就是這樣，白追了一輪。）
    """
    vvp = os.path.join(OUT, f"gl_{tag}.vvp")

    with open(netlist) as f:
        cells = sorted(set(re.findall(r"sky130_fd_sc_hd__[a-z0-9_]+", f.read())))

    filelist = os.path.join(OUT, f"cells_{tag}.f")
    incs = []
    with open(filelist, "w") as f:
        for c in cells:
            hits = subprocess.run(
                ["find", os.path.join(MODELS, "cells"), "-name", f"{c}.v"],
                capture_output=True, text=True).stdout.split()
            if hits:
                f.write(hits[0] + "\n")
                incs.append("-I" + os.path.dirname(hits[0]))

    # FUNCTIONAL：選 .functional.v（無需 SDF 反標註的 specify timing）
    # UNIT_DELAY=#1：讓結構性 hazard（glitch）能傳播。零延遲完全沒有 glitch，
    #               會系統性低估動態功耗。
    # 不定義 USE_POWER_PINS：Yosys 的 netlist 沒有 power pin。
    cmd = ["iverilog", "-g2012", "-DFUNCTIONAL", "-DUNIT_DELAY=#1", "-DGATE_LEVEL",
           f"-Ptb_viterbi_file.Q={Q}", f"-Ptb_viterbi_file.W={W}",
           f"-Ptb_viterbi_file.D={D}", f"-Ptb_viterbi_file.NINFO={ninfo}",
           *sorted(set(incs)),
           "-o", vvp, "-f", filelist, netlist,
           os.path.join(REPO, "tb", "gl", "tb_viterbi_file.sv"),
           "-s", "tb_viterbi_file"]
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"iverilog 失敗 ({tag}):\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    return vvp, len(cells)


def run_saif(tag, vvp, sp, dp, T, snr, frames=None, depth=3):
    """跑 gate-level 模擬，VCD 經 FIFO 串流轉成 SAIF（VCD 永不落地）。"""
    frames = FRAMES if frames is None else frames
    # frames **必須**進檔名。第一版沒放，於是收斂性用的 1/2-frame run
    # 靜靜覆寫了主 run（3 frame）的 SAIF：功耗數字沒錯（當下是用正確的 SAIF 算的），
    # 但歸檔下來的 SAIF 與所報的功耗對不起來——而文件宣稱 SAIF「可入庫當證據」。
    saif = os.path.join(SAIF_DIR, f"act_{tag}_snr{snr}_f{frames}.saif")
    os.makedirs(SAIF_DIR, exist_ok=True)
    fifo = os.path.join(OUT, f"dump_{tag}_{snr}.vcd")
    if os.path.exists(fifo):
        os.remove(fifo)
    os.mkfifo(fifo)

    conv = subprocess.Popen(
        [sys.executable, os.path.join(REPO, "ppa", "vcd2saif.py"),
         "--vcd", fifo, "--out", saif],
        stderr=subprocess.PIPE, text=True, cwd=REPO)

    t0 = time.time()
    sim = subprocess.run(
        ["vvp", vvp, f"+stim={sp}", f"+dec={dp}", f"+frames={frames}",
         f"+vcd={fifo}", f"+dumpdepth={depth}"],
        capture_output=True, text=True, cwd=REPO)
    _, conv_err = conv.communicate()
    dt = time.time() - t0
    os.remove(fifo)

    ok = "TB_RESULT PASS" in sim.stdout
    n_nets = 0
    m = re.search(r"vcd2saif: (\d+) nets", conv_err or "")
    if m:
        n_nets = int(m.group(1))

    return saif, ok, n_nets, dt, sim.stdout


def run_sta(tag, netlist, saif, snr):
    """OpenSTA：SAIF 標註 + 總體與分區塊功耗。"""
    tcl = os.path.join(OUT, f"pwr_{tag}_{snr}.tcl")
    rel_net = "/work/" + os.path.relpath(netlist, REPO)
    rel_saif = "/work/" + os.path.relpath(saif, REPO)

    lines = [
        f"read_liberty {LIB}",
        f"read_verilog {rel_net}",
        "link_design viterbi_top",
        f"create_clock -name clk -period {CLK_NS} [get_ports clk]",
        # -scope 是成敗關鍵：SAIF 的根是 testbench，設計的根是 viterbi_top。
        # 打錯 -> 0% annotation，而症狀會偽裝成「功耗竟然不隨輸入改變」。
        f"read_saif -scope tb_viterbi_file/dut {rel_saif}",
        'puts "=== ANNOTATION ==="',
        "report_activity_annotation",
        'puts "=== POWER TOTAL ==="',
        "report_power -digits 6",
    ]
    for b in BLOCKS:
        lines += [f'puts "=== POWER {b} ==="',
                  f"report_power -digits 6 -instances [get_cells {b}]"]
    lines.append("exit")

    with open(tcl, "w") as f:
        f.write("\n".join(lines) + "\n")

    p = subprocess.run(
        ["bash", os.path.join(REPO, "ppa", "orfs.sh"),
         f"sta -no_init -exit /work/{os.path.relpath(tcl, REPO)}"],
        cwd=REPO, capture_output=True, text=True)
    return p.stdout + p.stderr


def parse_power(txt):
    """從 OpenSTA 的輸出解析 annotation 覆蓋率與各區塊的功耗。"""
    res = {}

    # annotation
    blk = re.search(r"=== ANNOTATION ===(.*?)===", txt, re.S)
    if blk:
        counts = {}
        for line in blk.group(1).splitlines():
            m = re.match(r"\s*([A-Za-z_][A-Za-z_ ]*?)\s+(\d+)\s*$", line)
            if m:
                counts[m.group(1).strip().lower()] = int(m.group(2))
        un = counts.pop("unannotated", 0)
        an = sum(counts.values())
        res["annot_pct"] = 100.0 * an / (an + un) if (an + un) else 0.0

    # 兩種輸出格式不一樣（實測，不是猜的）：
    #
    #   report_power（全設計）  -> 有分組表格，最後一列是 "Total <int> <sw> <leak> <tot>"
    #   report_power -instances -> 沒有 "Total" 標籤，數字在**前**、實例名在後：
    #                              " 2.548474e-02 3.988741e-03 6.129220e-08 2.947354e-02 u_tb"
    NUM = r"[\d.]+e[+-]\d+"

    def _total_section(section):
        b = re.search(rf"=== POWER {section} ===(.*?)(?:===|\Z)", txt, re.S)
        if not b:
            return None
        m = re.search(rf"^Total\s+({NUM})\s+({NUM})\s+({NUM})\s+({NUM})",
                      b.group(1), re.M)
        if not m:
            return None
        return {"internal": float(m.group(1)), "switching": float(m.group(2)),
                "leakage": float(m.group(3)), "total": float(m.group(4))}

    def _inst_section(section, inst):
        b = re.search(rf"=== POWER {section} ===(.*?)(?:===|\Z)", txt, re.S)
        if not b:
            return None
        m = re.search(rf"^\s*({NUM})\s+({NUM})\s+({NUM})\s+({NUM})\s+{re.escape(inst)}\s*$",
                      b.group(1), re.M)
        if not m:
            return None
        return {"internal": float(m.group(1)), "switching": float(m.group(2)),
                "leakage": float(m.group(3)), "total": float(m.group(4))}

    res["total"] = _total_section("TOTAL")
    for b in BLOCKS:
        res[b] = _inst_section(b, b)
    return res
