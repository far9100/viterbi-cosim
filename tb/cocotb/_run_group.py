"""_run_group.py — 跑一組 (Q, W, D)。由 run_tier_a.py 以 subprocess 呼叫。

## 為什麼要另開一個 process

cocotb 的 runner 是把模擬器**當成子行程**啟動的，模擬器的 stdout/stderr 直接繼承
父行程的檔案描述子。所以在 Python 這一層做 `redirect_stdout` **抓不到模擬器的輸出**。

第一版就是這樣寫的，後果很嚴重：`"G6 violated" in out` 永遠是 False，
於是 **G6 的負向測試會報告「assertion 沒有觸發」——即使它其實觸發了**。
一個哨兵如果偵測不到自己有沒有響，那它就不是哨兵。

改成用 subprocess 跑這支檔案，再用 capture_output 抓，就連子行程的輸出都收得到。
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

# RTL 目錄可切換。rtl_lowpower/ 是 M9 的 B0'/B1' 所合成的原始碼，也就是
# -42.7% 功耗與 -11.02% 面積這些**已發表數字的來源**，但它先前完全不進 Tier A ——
# 唯一的檢查是閘級的 verify_cg，而那道檢查在 M10 之前還驗錯了 netlist。
# 兩份 RTL 宣稱語意等價（差別只有 reset 寫法：if (rst || en) 對 if (rst) / else if (en)），
# 那是一個可以**驗證**的宣稱，不該只是註解。
RTL_DIR = os.environ.get("FEC_RTL_DIR", "rtl")
MODULES = ["bmu.sv", "acs_butterfly.sv", "acs_array.sv", "minpm.sv",
           "traceback.sv", "ctrl.sv", "viterbi_top.sv"]
RTL = [RTL_DIR + "/" + m for m in MODULES] + ["tb/dbg/viterbi_dbg.sv"]


def main():
    from cocotb.runner import get_runner

    sim = os.environ["FEC_SIM"]
    Q = int(os.environ["FEC_Q"])
    W = int(os.environ["FEC_W"])
    D = int(os.environ["FEC_D"])
    ninfo = int(os.environ["FEC_NINFO"])
    workdir = os.environ["FEC_WORKDIR"]

    runner = get_runner(sim)
    want_assert = os.environ.get("FEC_ASSERT", "1") == "1"
    if sim == "verilator":
        build_args = ["-Wno-fatal", "--x-assign", "fast", "--x-initial", "fast"]
        if want_assert:
            build_args.insert(0, "--assert")
        else:
            # Verilator 5.x 連沒有 --assert 都會執行 immediate assertion 然後 $stop，
            # 所以要用 define 把它整段編掉，C2 才跑得完。
            build_args.append("-DG6_OFF")
    else:
        build_args = ["-g2012"] + ([] if want_assert else ["-DG6_OFF"])

    runner.build(
        verilog_sources=[os.path.join(REPO, f) for f in RTL],
        includes=[os.path.join(REPO, RTL_DIR)],
        hdl_toplevel="viterbi_dbg",
        parameters={"Q": Q, "W": W, "D": D, "NINFO": ninfo},
        build_dir=workdir, build_args=build_args, always=True,
    )
    runner.test(
        # 測試模組可切換：Tier A 現在有兩支 testbench —— `test_viterbi`（C2，資料路徑）
        # 與 `test_ctrl`（控制路徑：stall / frame_done / 幀中 reset / 背靠背）。
        hdl_toplevel="viterbi_dbg",
        test_module=os.environ.get("FEC_TEST_MODULE", "test_viterbi"),
        build_dir=workdir,
        test_dir=os.path.join(REPO, "tb", "cocotb"),
        extra_env=dict(os.environ),
        results_xml=os.path.join(workdir, "results.xml"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
