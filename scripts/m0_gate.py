"""m0_gate.py — M0（環境建置）的驗收閘門。

M0 不是「裝一裝就好」的階段。規格書把 Verilator / cocotb / OpenLane / SAIF 流程
全都當成既有資產，但實測下來：Verilator、cocotb、torch 在這台機器上都不存在，
Windows 連 g++ 都沒有，而 RISC-V 專案的 VCD->SAIF->OpenSTA 功耗流程**從未被建置過**
（它的功耗是 vectorless 的假設值）。所以 M0 有真正要驗收的東西。

三道 gate：

  E1  RTL 工具鏈就位（Verilator + Icarus 雙模擬器；後者是 G7 的 4-state 交叉檢查所需）
  E2  GPU 整數路徑可用（sm_120），且與 numpy 逐位元組相等——含平手情形
  E3  Gate-level 功耗流程打通：annotation coverage >= 99%

E3 是其中最重要的一道。它與解碼器毫無相依，卻是全專案唯一零複用、未知數最多的部分。
在第 1 週把它跑通，代表 M5 不會再有「annotation 是 0%」這種會讓頭條結果報銷的意外。
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gates import REPO, Run  # noqa: E402


def sh(cmd):
    try:
        out = subprocess.run(cmd, shell=True, cwd=REPO, capture_output=True,
                             timeout=1800)
        return out.returncode, (out.stdout + out.stderr).decode(errors="replace")
    except Exception as e:
        return 1, str(e)


def main():
    run = Run("m0_env", milestone="M0")

    print("=== E1  RTL 工具鏈")
    rc_v, out_v = sh("verilator --version")
    rc_i, out_i = sh("iverilog -V")
    ver_v = out_v.strip().splitlines()[0] if rc_v == 0 else "MISSING"
    ver_i = out_i.strip().splitlines()[0] if rc_i == 0 else "MISSING"
    run.check(
        "E1 Verilator + Icarus", rc_v == 0 and rc_i == 0,
        measured=f"{ver_v} / {ver_i}", expected="兩者皆在",
        detail="需要兩個模擬器：Verilator 是 2-state（未初始化的暫存器讀為 0），"
               "會隱藏 reset 不完整的 bug；Icarus 是 4-state（讀為 X）。G7 靠它交叉檢查。",
    )

    print("\n=== E2  GPU 整數路徑（sm_120）")
    rc_g, out_g = sh(".venv/bin/python scripts/gpu_smoke.py")
    cap = re.search(r"compute capability\s+(sm_\d+)", out_g)
    ties = re.search(r"平手樣本數\s+(\d+)", out_g)
    run.check(
        "E2 GPU 整數 ACS 位元級相等", rc_g == 0,
        measured=f"{cap.group(1) if cap else '?'}, 平手樣本 {ties.group(1) if ties else 0}",
        expected="sm_120, 與 numpy array_equal",
        detail="平手樣本數必須 > 0，否則 tie-break 語意根本沒被測到。"
               "torch.minimum 不回傳索引，<= 與 < 的選擇會默默決定平手方向——"
               "這是 C2' 最可能的失效點。",
    )

    print("\n=== E3  Gate-level 功耗流程")
    log = os.path.join(REPO, "ppa/out/smoke/power.log")
    if not os.path.exists(log):
        rc_p, _ = sh("bash scripts/m0_smoke.sh")
    rc_a, out_a = sh(f".venv/bin/python ppa/check_annotation.py {log}")
    m = re.search(r"=\s*([\d.]+)%", out_a)
    pct = float(m.group(1)) if m else 0.0
    run.check(
        "E3 SAIF annotation coverage", pct >= 99.0,
        measured=f"{pct:.2f}%", expected=">= 99%",
        detail="Yosys -> Icarus gate-level -> VCD -> SAIF -> OpenSTA 全線打通。"
               "覆蓋率不足時 OpenSTA 不會報錯，只會靜靜地套用預設 toggle-rate 猜測——"
               "而規格書 §7 明令禁止那件事。",
    )

    return run.finalize()


if __name__ == "__main__":
    sys.exit(main())
