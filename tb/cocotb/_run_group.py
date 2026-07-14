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

RTL = [
    "rtl/bmu.sv", "rtl/acs_butterfly.sv", "rtl/acs_array.sv", "rtl/minpm.sv",
    "rtl/traceback.sv", "rtl/ctrl.sv", "rtl/viterbi_top.sv",
    "tb/dbg/viterbi_dbg.sv",
]


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
        includes=[os.path.join(REPO, "rtl")],
        hdl_toplevel="viterbi_dbg",
        parameters={"Q": Q, "W": W, "D": D, "NINFO": ninfo},
        build_dir=workdir, build_args=build_args, always=True,
    )
    runner.test(
        hdl_toplevel="viterbi_dbg", test_module="test_viterbi",
        build_dir=workdir,
        test_dir=os.path.join(REPO, "tb", "cocotb"),
        extra_env=dict(os.environ),
        results_xml=os.path.join(workdir, "results.xml"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
