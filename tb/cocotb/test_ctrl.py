"""test_ctrl.py — 控制路徑的定向驗證（Tier A 的第二支 testbench）。

## 為什麼需要它：資料路徑被驗到爆，控制路徑一次都沒被碰過

C2 把 `bm` / `pm` / `survivor` / 解碼位元在 2.47 億個 stage 上驗到零 mismatch。
但**所有的 testbench 都用同一種方式驅動 DUT**：`in_valid` 連續拉高 T 個 cycle、
只在 frame 開頭 reset 一次、frame 之間一定重 reset。於是控制路徑上有四件事
從來沒有被激勵過：

1. **`in_valid` 在 frame 中途拉低（stall）。** `rtl/ctrl.sv` 的
   `stage_en = (st == S_RUN) && in_valid` 明確支援它，而 `stage_en` 同時 gate 住
   **三個模組的四組暫存器**（`acs_array` 的 `pm` 與 `surv_r`、`traceback` 的 `re`、
   `viterbi_top` 的 `bm_r`）；在 `rtl_lowpower/` 它更是 ICG 的 enable。
   一個 stall cycle 若讓其中任何一組錯拍，C2 完全看不到 —— 因為 C2 從來不 stall。

2. **`frame_done`。** 它是 `viterbi_top` 的輸出、被 dbg wrapper 拉出來、
   在 GL TB 裡接了線 —— 但 grep 全 repo，**沒有任何測試讀過它**。
   它可以恆為 0、可以在錯的 cycle 拉高、可以永遠不拉高，所有 gate 都還是綠的。

3. **frame 中途 reset。** 每個 TB 都只在 frame 開頭 reset。而 `rtl_lowpower/`
   的整個 reset-in-enable 改寫，存在的理由就是讓 reset 在 clock gating 下仍然進得去
   （`2026-07-29-17` 那個 bug）—— 卻沒有測試在 frame 中途按下 reset。

4. **不 reset 的背靠背 frame。** `ctrl.sv` 的 FSM 停在 `S_DONE` 直到 reset。
   這是一個**設計限制**，但先前沒有任何地方寫下來、也沒有測試釘住它。
   本檔把它變成一條會失敗的斷言：行為若改變（例如有人讓它自動回 S_RUN），
   這裡會叫，而不是讓一個未記載的行為悄悄變成相依。

## 判準

stall 那條的判準是**逐位元相同**：有 stall 與沒有 stall 的解碼位元串流必須一模一樣。
這比「與 golden 相同」更嚴格一點的地方在於它同時釘住「stall 不改變任何東西」，
而不只是「stall 之後結果仍正確」。
"""

import json
import os
import random
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

T = NINFO + 6
STALL_SEED = 20260801        # 固定 seed：stall 的位置必須可重現


async def _reset(dut, cycles=3):
    dut.rst.value = 1
    dut.in_valid.value = 0
    dut.r0.value = 0
    dut.r1.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def _drive(dut, rq_frame, stalls=None, max_extra=None):
    """餵一個 frame，回傳 (解碼位元, frame_done 脈衝數, stage_done 次數)。

    stalls：一個 set，裡面的 **stage 編號** 之前會插入一個 in_valid=0 的空拍。
    stall 不消耗 stage —— 這正是要驗的：空拍不得讓任何暫存器前進。
    """
    extra = max_extra if max_extra is not None else D + 4
    dec_bits = []
    n_done = 0
    n_stage = 0
    fed = 0
    stalls = stalls or set()
    stalled = set()

    for _ in range(T + extra + len(stalls)):
        if fed < T and fed in stalls and fed not in stalled:
            # 插入一個空拍：in_valid=0，資料保持不變
            stalled.add(fed)
            dut.in_valid.value = 0
        elif fed < T:
            dut.in_valid.value = 1
            dut.r0.value = int(rq_frame[fed, 0])
            dut.r1.value = int(rq_frame[fed, 1])
            fed += 1
        else:
            dut.in_valid.value = 0

        await RisingEdge(dut.clk)

        if int(dut.dbg_stage_done.value) == 1:
            n_stage += 1
        if int(dut.out_valid.value) == 1:
            dec_bits.append(int(dut.dec_bit.value))
        if int(dut.frame_done.value) == 1:
            n_done += 1

    return dec_bits, n_done, n_stage


def _load():
    """取第一個凍結向量的第一個 frame 當激勵，並算出 golden 解碼位元。"""
    name = VECTORS[0]
    z = np.load(os.path.join(REPO, "vectors", f"{name}.npz"))
    rq = z["rq"].astype(np.int64)
    assert int(z["Q"]) == Q and int(z["W"]) == W and int(z["D"]) == D
    gold = decode_fx(rq, viterbi_trellis(), Q, W, D, NINFO,
                     mode="window", check_g6=False, keep_history=False)
    return name, rq[0], gold["dec"][0].tolist()


@cocotb.test()
async def test_ctrl_paths(dut):
    """四條控制路徑的定向測試。任何一條失敗都是零容忍。"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    name, frame, exp_dec = _load()
    dut._log.info(f"控制路徑測試：Q={Q} W={W} D={D}，激勵取自 {name} 的 frame 0")

    # ---------------------------------------------------------------- 1. 基準
    await _reset(dut)
    base_dec, base_done, base_stage = await _drive(dut, frame)
    assert base_stage == T, f"基準：只看到 {base_stage} 個 stage_done，預期 {T}"
    assert len(base_dec) == T, f"基準：收到 {len(base_dec)} 個解碼位元，預期 {T}"
    assert base_dec[:NINFO] == exp_dec, "基準：解碼位元與 golden 不符"

    # ---------------------------------------------------------------- 2. frame_done
    #
    # 先前沒有任何測試讀過這個訊號。它必須**恰好拉高一次**。
    assert base_done == 1, (
        f"frame_done 拉高了 {base_done} 次，預期恰好 1 次。"
        f"（它是 viterbi_top 的輸出，卻從來沒有被任何測試讀過——"
        f"恆為 0 或在錯的 cycle 拉高，先前所有 gate 都還是綠的。）")
    dut._log.info("  [PASS] frame_done 恰好拉高一次")

    # ---------------------------------------------------------------- 3. stall
    #
    # 在 frame 中途隨機插入 32 個空拍。判準是**逐位元相同**：
    # stall 不得改變任何一個解碼位元，也不得改變 stage 的總數。
    rng = random.Random(STALL_SEED)
    stalls = set(rng.sample(range(1, T - 1), 32))
    await _reset(dut)
    st_dec, st_done, st_stage = await _drive(dut, frame, stalls=stalls)

    assert st_stage == T, (
        f"stall：看到 {st_stage} 個 stage_done，預期 {T}。"
        f"**空拍讓 stage 前進了**——stage_en 沒有正確 gate 住。")
    assert st_dec == base_dec, (
        f"stall：解碼位元與無 stall 時不同。"
        f"in_valid 中途拉低會 gate 住三個模組的四組暫存器"
        f"（pm / surv_r / re / bm_r），其中任何一組錯拍都會在這裡出現。")
    assert st_done == 1, f"stall：frame_done 拉高了 {st_done} 次，預期 1 次"
    dut._log.info(f"  [PASS] {len(stalls)} 個 stall 空拍：解碼位元逐位元相同")

    # ---------------------------------------------------------------- 4. 幀中 reset
    #
    # 餵一半就 reset，再從頭餵完整的一幀。結果必須與從未被打斷過一樣。
    await _reset(dut)
    for cyc in range(T // 2):
        dut.in_valid.value = 1
        dut.r0.value = int(frame[cyc, 0])
        dut.r1.value = int(frame[cyc, 1])
        await RisingEdge(dut.clk)

    await _reset(dut)              # frame 中途按下 reset
    rs_dec, rs_done, rs_stage = await _drive(dut, frame)

    assert rs_stage == T, f"幀中 reset：看到 {rs_stage} 個 stage_done，預期 {T}"
    assert rs_dec == base_dec, (
        "幀中 reset 之後重新灌一整幀，結果與基準不同——"
        "有暫存器沒有被 reset 乾淨。這正是 rtl_lowpower/ 的 reset-in-enable "
        "改寫要保護的東西（見 `2026-07-29-17`），卻一直沒有測試碰過它。")
    assert rs_done == 1, f"幀中 reset：frame_done 拉高了 {rs_done} 次，預期 1 次"
    dut._log.info("  [PASS] 幀中 reset 後重新灌一整幀，結果與基準逐位元相同")

    # ---------------------------------------------------------------- 5. 背靠背
    #
    # **這一條斷言的是設計限制，不是功能。** ctrl.sv 的 FSM 跑完停在 S_DONE
    # 直到 reset；所以不 reset 直接餵第二幀，不會有任何新的輸出。
    # 把它釘住的理由：這個限制先前沒有寫在任何地方，也沒有測試保護。
    # 若將來有人讓 FSM 自動回到 S_RUN，這裡會叫——那時該做的是同時更新
    # docs/report.md §5 的限制清單，而不是默默接受一個未記載的新行為。
    b2b_dec, b2b_done, b2b_stage = await _drive(dut, frame, max_extra=0)
    assert b2b_stage == 0 and not b2b_dec and b2b_done == 0, (
        f"不 reset 的第二幀產生了輸出（stage={b2b_stage}、"
        f"位元={len(b2b_dec)}、frame_done={b2b_done}）。"
        f"ctrl.sv 目前的設計是停在 S_DONE 直到 reset；"
        f"行為若改變，docs/report.md §5 的限制清單要同步更新。")
    dut._log.info("  [PASS] 不 reset 的背靠背幀：無輸出（已記載的設計限制）")

    # 這行給 run_tier_a.py 抓
    print(f"CTRL_STATS {Q} {W} {D} 4 {len(stalls)}")
