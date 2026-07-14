"""export_vectors_hex.py — 把凍結向量與 golden 的期望輸出匯出成 $readmemh 檔。

## 為什麼需要一條「不經過 Python」的路

1. **G7（4-state 交叉檢查）**：Icarus 是唯一的 4-state 模擬器，但 oss-cad-suite 的
   iverilog/vvp 自帶一整套 glibc（RPATH 指向自己的 lib）。cocotb 的 VPI 要 dlopen
   系統的 libpython3.12，而後者需要 GLIBC_2.38——oss-cad-suite 的 libm 太舊，
   直接爆掉。裝系統版 iverilog 需要 root。
   繞法：**Icarus 這一側完全不要 Python**。用 $readmemh 讀檔案驅動就好。

2. **M5 的 gate-level 模擬**：合成後的 netlist 只能用 Icarus 跑（sky130 的 cell model
   建在 UDP / specify 之上，Verilator 不支援），而 cocotb 也接不上 gate-level netlist。
   所以無論如何都需要一支「檔案驅動」的 testbench。

一支 TB 同時服務兩件事。
"""

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.trellis import viterbi_trellis  # noqa: E402
from golden.viterbi_fx import decode_fx  # noqa: E402
from scripts.gates import REPO  # noqa: E402

OUT = os.path.join(REPO, "tb", "gl", "vectors")


def export(name):
    z = np.load(os.path.join(REPO, "vectors", f"{name}.npz"))
    rq = z["rq"].astype(np.int64)
    Q, W, D = int(z["Q"]), int(z["W"]), int(z["D"])
    ninfo = int(z["n_info"])
    B, T, _ = rq.shape

    t = viterbi_trellis()
    gold = decode_fx(rq, t, Q, W, D, ninfo, mode="window",
                     check_g6=False, keep_history=False)

    os.makedirs(OUT, exist_ok=True)

    # 激勵：每行一個 stage，"<r0> <r1>"（十六進位）。所有 frame 接在一起。
    with open(os.path.join(OUT, f"{name}_stim.hex"), "w") as f:
        for b in range(B):
            for tt in range(T):
                f.write(f"{rq[b, tt, 0]:x} {rq[b, tt, 1]:x}\n")

    # 期望的解碼位元：每行一個 bit。所有 frame 接在一起。
    with open(os.path.join(OUT, f"{name}_dec.hex"), "w") as f:
        for b in range(B):
            for i in range(ninfo):
                f.write(f"{int(gold['dec'][b, i])}\n")

    return {"name": name, "Q": Q, "W": W, "D": D,
            "n_info": ninfo, "n_frames": B, "T": T}


def main():
    names = sys.argv[1:] or ["directed_allzero", "directed_allone",
                             "directed_impulse", "directed_burst",
                             "rand_Q4_W10_D32", "boundary_Q4_W10"]
    meta = [export(n) for n in names]
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump(meta, f, indent=2)
    for m in meta:
        print(f"  {m['name']:22s} Q={m['Q']} W={m['W']:2d} D={m['D']:2d}  "
              f"{m['n_frames']} frames x {m['T']} stages")
    print(f"\n匯出到 {OUT}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
