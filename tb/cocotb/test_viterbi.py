"""test_viterbi.py — Tier A：C2 的逐 stage 位元級比對。

## 這是本專案的核心閘門（G5 = C2）

每個 trellis stage 結束時，把 DUT 的 `bm[4]` / `pm[64]` / `survivor[64]` 拉出來，
與 golden model 逐位元比對；frame 結束時再比對整條解碼位元串流。**零容忍。**

## 為什麼解碼位元也要比

C2 若只比 bm/pm/survivor，**traceback 策略不同會改變 BER，卻完全通得過 C2**——
兩邊的架構狀態一模一樣，但從那些狀態導出解碼位元的方式不同。
所以解碼位元被納入比對集（規格書修訂）。

## 為什麼用 stage_done 這個脈衝觸發比對，而不是數 cycle

RTL 內部怎麼 pipeline、一個 stage 花幾個 cycle，是 RTL 自己的事（規格書 §2.1：
bit-accurate 不要求 cycle-accurate）。比對只發生在**架構狀態邊界**上。
用脈衝觸發的另一個好處：將來的折疊架構（PAR=8 / PAR=1，一個 stage 要好幾個 cycle）
可以完全沿用這套 testbench，**零新程式碼**。

## 激勵來自 M1 凍結的測試向量

`vectors/*.npz` 的輸入是逐位元組凍結的，期望輸出由 SHA-256 釘住
（`vectors/MANIFEST.json`）。cocotb 在這裡**直接 import golden model**，
同一份 numpy 程式碼同時驅動 DUT 與參考——不經過檔案匯出（規格書 §4 Tier A）。
"""

import json
import os
import sys

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

REPO = os.environ.get("FEC_REPO", os.path.expanduser("~/fec-cosim"))
sys.path.insert(0, REPO)

from golden.trellis import viterbi_trellis  # noqa: E402
from golden.viterbi_fx import decode_fx  # noqa: E402

Q = int(os.environ["FEC_Q"])
W = int(os.environ["FEC_W"])
D = int(os.environ["FEC_D"])
NINFO = int(os.environ["FEC_NINFO"])
VECTORS = os.environ["FEC_VECTORS"].split(",")

BM_W = Q + 1
NSTATES = 64
T = NINFO + 6


def _unpack(val, n, width):
    """把一個寬 handle 的值拆成 n 個 width 位元的欄位（LSB 是第 0 個）。"""
    v = int(val)
    mask = (1 << width) - 1
    return [(v >> (i * width)) & mask for i in range(n)]


async def _reset(dut):
    dut.rst.value = 1
    dut.in_valid.value = 0
    dut.r0.value = 0
    dut.r1.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def _run_frame(dut, rq_frame, gold, f_idx, name):
    """跑一個 frame，逐 stage 比對 bm / pm / surv，最後比對整條解碼位元。"""
    await _reset(dut)

    dec_bits = []
    stage = 0
    mismatches = 0

    # 連續餵 T 個 stage；stage_done 會比 in_valid 晚一個 cycle。
    # 之後還要等 1 (S_LAST) + (D-1) (S_FLUSH) 個 cycle 把尾端沖完。
    for cyc in range(T + D + 4):
        if cyc < T:
            dut.in_valid.value = 1
            dut.r0.value = int(rq_frame[cyc, 0])
            dut.r1.value = int(rq_frame[cyc, 1])
        else:
            dut.in_valid.value = 0

        await RisingEdge(dut.clk)

        # ---- C2：在 stage_done 這個脈衝上比對架構狀態 ----
        if int(dut.dbg_stage_done.value) == 1:
            assert stage < T, f"{name}: stage_done 多於 T={T} 次"

            got_bm = _unpack(dut.dbg_bm.value, 4, BM_W)
            got_pm = _unpack(dut.dbg_pm.value, NSTATES, W)
            got_sv = _unpack(dut.dbg_surv.value, NSTATES, 1)
            got_best = int(dut.dbg_best.value)

            exp_bm = gold["bm"][f_idx, stage].tolist()
            exp_pm = gold["pm"][f_idx, stage].tolist()
            exp_sv = gold["surv"][f_idx, stage].tolist()
            exp_best = int(gold["best"][f_idx, stage])

            if got_bm != exp_bm:
                mismatches += 1
                raise AssertionError(
                    f"C2 bm mismatch @ {name} frame {f_idx} stage {stage}\n"
                    f"  RTL    {got_bm}\n  golden {exp_bm}")
            if got_pm != exp_pm:
                bad = [(s, got_pm[s], exp_pm[s])
                       for s in range(NSTATES) if got_pm[s] != exp_pm[s]]
                raise AssertionError(
                    f"C2 pm mismatch @ {name} frame {f_idx} stage {stage}\n"
                    f"  {len(bad)} / 64 個狀態不同，前 5 個 (state, RTL, golden): {bad[:5]}")
            if got_sv != exp_sv:
                bad = [s for s in range(NSTATES) if got_sv[s] != exp_sv[s]]
                raise AssertionError(
                    f"C2 survivor mismatch @ {name} frame {f_idx} stage {stage}\n"
                    f"  不同的狀態: {bad[:10]}")
            if got_best != exp_best:
                raise AssertionError(
                    f"C2 best(min-PM) mismatch @ {name} frame {f_idx} stage {stage}: "
                    f"RTL {got_best} vs golden {exp_best}")

            stage += 1

        if int(dut.out_valid.value) == 1:
            dec_bits.append(int(dut.dec_bit.value))

    assert stage == T, f"{name}: 只看到 {stage} 個 stage_done，預期 {T}"
    assert len(dec_bits) == T, \
        f"{name}: 收到 {len(dec_bits)} 個解碼位元，預期 {T}"

    # ---- C2：解碼位元（traceback 策略不同會改 BER 卻通過 bm/pm/surv 的比對）----
    exp_dec = gold["dec"][f_idx].tolist()
    got_dec = dec_bits[:NINFO]
    if got_dec != exp_dec:
        bad = [i for i in range(NINFO) if got_dec[i] != exp_dec[i]]
        raise AssertionError(
            f"C2 解碼位元 mismatch @ {name} frame {f_idx}: "
            f"{len(bad)} / {NINFO} 個位元不同，前 10 個位置 {bad[:10]}")

    return T


@cocotb.test()
async def test_c2_per_stage(dut):
    """C2：對每個凍結向量的每個 frame、每個 stage，比對 bm / pm / survivor / 解碼位元。"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    t = viterbi_trellis()
    with open(os.path.join(REPO, "vectors", "MANIFEST.json")) as f:
        manifest = {v["name"]: v for v in json.load(f)["vectors"]}

    n_frames = n_stages = 0
    for name in VECTORS:
        z = np.load(os.path.join(REPO, "vectors", f"{name}.npz"))
        rq = z["rq"].astype(np.int64)
        assert int(z["Q"]) == Q and int(z["W"]) == W and int(z["D"]) == D
        assert int(z["n_info"]) == NINFO

        # cocotb 直接 import golden model —— 同一份 numpy 程式碼同時驅動 DUT 與參考
        gold = decode_fx(rq, t, Q, W, D, NINFO, mode="window",
                         check_g6=False, keep_history=True)

        for f_idx in range(rq.shape[0]):
            n_stages += await _run_frame(dut, rq[f_idx], gold, f_idx, name)
            n_frames += 1

        dut._log.info(f"  {name}: {rq.shape[0]} frames x {T} stages —— 零 mismatch")

    dut._log.info(
        f"C2 通過：{len(VECTORS)} 個向量 / {n_frames} 個 frame / "
        f"{n_stages} 個 stage 比對，0 mismatch （Q={Q} W={W} D={D}）")

    # 這行給 run_tier_a.py 抓，用來彙整 C2 的統計
    print(f"C2_STATS {Q} {W} {D} {n_frames} {n_stages}")
