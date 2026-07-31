"""verify_cg.py — clock-gated netlist 的 C2 驗證（**量功耗之前必須先過**）。

`docs/lowpower_baseline.md` §4.1 的硬性順序：B1/B2 改變合成或架構之後，
**先過 C2，才准量功耗**。理由不是形式主義——

    Yosys 的 `clockgate` pass 把「有 enable 的 FF」換成「無 enable 的 FF + ICG」。
    sky130 的 ICG 是 **latch-based**（`clock_gating_integrated_cell : "latch_posedge"`），
    它在 CLK 為低時對 GATE 取樣。如果 enable 訊號在 CLK 低相位有毛刺，
    gated clock 就會多出或少掉一個邊緣 —— 而症狀是**解碼位元錯幾個**，
    功耗數字看起來完全正常。

    一個功能壞掉的 netlist 照樣會產生 SAIF、照樣會被 OpenSTA 算出功耗、
    照樣會畫出漂亮的圖。C2 是唯一擋得住這件事的東西。

用 `tb/gl/tb_viterbi_file.sv`（M5 與 G7 共用的檔案驅動 TB）：它自己比對解碼位元（C2）
並偵測 X/Z（G7）。不 dump VCD —— 純功能檢查不需要，而 VCD 是慢的那一段。
"""

import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ppa.power as P  # noqa: E402
from scripts.gates import REPO  # noqa: E402

OUT = os.path.join(REPO, "ppa", "out", "power")


def check(Q, W, D, clip, snr=3.0, frames=1, cg=False):
    """建置並跑 gate-level 功能檢查。回傳 (通過?, 比對的位元數, 摘要)。"""
    tag = f"Q{Q}_W{W}_D{D}" + ("_cg" if cg else "")
    netlist = os.path.join(REPO, "ppa", "out", "synth", f"net_{tag}.v")
    if not os.path.exists(netlist):
        return False, 0, f"netlist 不存在：{netlist}"

    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        # 激勵與 B0 完全相同（同一個 seed、同一支 make_stimulus）——
        # 兩態的差異才能歸因於合成選項，而不是輸入不同。
        sp, dp, T = P.make_stimulus(Q, W, D, clip, snr, td)
        vvp, n_cells = P.build_gl(tag + "_vfy", netlist, Q, W, D, P.NINFO)
        p = subprocess.run(
            ["vvp", vvp, f"+stim={sp}", f"+dec={dp}", f"+frames={frames}"],
            cwd=REPO, capture_output=True, text=True, timeout=3600)

    txt = p.stdout + p.stderr
    m = re.search(r"TB_RESULT (PASS|FAIL) (\d+) (\d+)", txt)
    if not m:
        return False, 0, f"TB 沒有回報結果：\n{txt[-1500:]}"
    ok = m.group(1) == "PASS"
    n_checked = int(m.group(3)) if ok else 0
    err = re.search(r"C2 錯誤\s+(\d+)", txt)
    xz = re.search(r"X/Z 錯誤\s+(\d+)", txt)
    return ok, n_checked, (f"cells={n_cells} C2錯={err.group(1) if err else '?'} "
                           f"X/Z錯={xz.group(1) if xz else '?'}")


if __name__ == "__main__":
    CONFIGS = [(3, 8, 32, 2.0), (6, 12, 32, 3.0),
               (4, 10, 64, 2.5), (6, 12, 64, 3.0)]
    rc = 0
    for Q, W, D, clip in CONFIGS:
        ok, n, info = check(Q, W, D, clip, cg=True)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] Q{Q}_W{W}_D{D}_cg  比對 {n} 個解碼位元  {info}", flush=True)
        if not ok:
            rc = 1
    print("\nclock-gated netlist 的 C2：" + ("全部通過" if rc == 0 else "**有失敗，不得量功耗**"))
    sys.exit(rc)
