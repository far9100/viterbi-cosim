"""verify_b2_schedule.py — B2 硬體排程的逐拍原型，在寫 SystemVerilog 之前把指標算術驗對。

`scripts/verify_batch_memory.py` 用窮舉證明環狀緩衝要 3D（勘誤 E-06），但它只檢查
「索引會不會撞」，不產生解碼位元。本檔更進一步：**把打算合成出來的那個硬體逐拍模擬一遍**，
再把它吐出來的位元序列與 `golden.traceback(mode='batch')` 逐位元比對。

為什麼要先做這一步：B2 的指標算術有四層互相咬合的東西——環狀緩衝的模數、批次觸發點、
「留最舊的 D 個」的邊界、以及收集（由新到舊）與吐出（由舊到新）方向相反造成的 LIFO。
其中任何一處差一拍，症狀都是「解碼位元整體偏移」而不是明顯的壞掉，在 SystemVerilog
裡追這種問題非常貴；在 Python 裡是幾秒鐘的事。`docs/m14_implementation_notes.md` §5
記的那個第一版錯誤就屬於這一類。

模擬的是硬體，不是演算法：
  * `surv_mem` 是 3D 個 slot 的環狀緩衝（E-06）
  * 回溯引擎每拍走 2 步（一批 2D 步剛好佔滿 D 拍）
  * 兩個 D 位元的收集緩衝 ping-pong（第 N 批的吐出與第 N+1 批的收集完全重疊）
  * 尾端由終止狀態回溯，需要自己的 (D+m) 位元緩衝
  * 每拍最多吐 1 個位元，整個 frame 必須吐滿 T 個（tb/cocotb/test_viterbi.py 的契約）

**觸發晚一拍是硬體的限制，不是選擇**：RTL 的引擎跑在 `stage_en`（cycle C）上，
而那一拍讀到的 `best` 是 argmin(pm after stage t-1) = `best[t-1]`。要拿到 `best[t_end]`
只能等到 tick `t_end+1` —— 那一拍 `mem[t_end]` 也剛好寫進去了。這與
`verify_batch_memory.py` 假設的「引擎在 t_end+1 .. t_end+D 執行」一致。

本檔量出來、給 `ctrl.sv` 用的兩個數字：

    OUT_LAT = FLUSH_LEN = 3D - 1        （B0 / B1 是 D - 1）

`FLUSH_LEN == OUT_LAT` 在兩種回溯架構上同時成立，因為它們滿足同一條恆等式：
S_RUN 期間吐 `T - OUT_LAT` 個位元、flush 期間吐 `OUT_LAT` 個，合計恰好 T 個。
所以 `ctrl.sv` 只需要**一個**參數 —— `m14_implementation_notes.md` §3 原本寫成
兩個（`OUT_LAT` 與長度 `D+m` 的 flush），那個 `D+m` 是錯的。
"""

import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from golden.traceback import traceback  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from golden.viterbi_fx import decode_fx  # noqa: E402

M_BITS = 6          # VM = K - 1


def pred(sv_row, s):
    """一步回溯。與 golden/traceback.py::_pred 是同一條式子，刻意逐字對齊。"""
    return (s >> 1) | (int(sv_row[s]) << (M_BITS - 1))


def hw_batch(surv, best, D, mem_mult=3):
    """逐拍模擬 B2 硬體。回傳 (吐出的位元序列, 總 tick 數, 同時存在的緩衝數上限)。

    tick 0 .. T-1 是真正的 stage（有新的 survivor 寫入）；
    tick >= T 是 flush —— 沒有新輸入，但引擎與吐出繼續，直到吐滿 T 個位元。

    mem_mult : 環狀緩衝深度 = mem_mult x D。預設 3（E-06）；傳 2 可以看它怎麼壞。
    """
    T = surv.shape[0]
    MEM = mem_mult * D
    mem = np.zeros((MEM, surv.shape[1]), dtype=np.uint8)

    TAIL_LEN = D + M_BITS               # 尾端要解出的 stage 數
    out = []

    eng_active = False                  # 批次引擎
    eng_s = eng_k = eng_tend = 0
    eng_buf = []
    ready = []                          # 收滿、等待吐出的緩衝（FIFO）

    tail_pending = tail_active = False  # 尾端引擎
    tail_s = tail_j = 0
    tail_buf = []

    emitting = None
    emit_i = 0
    max_buf = 0

    tick = 0
    guard = 0
    while len(out) < T:
        guard += 1
        assert guard < 100 * T, "排程不收斂"

        # 1. survivor 寫入（只有真正的 stage 有）
        if tick < T:
            mem[tick % MEM] = surv[tick]

        # 2. 批次觸發：t_end = 2D-1, 3D-1, ...，但實際觸發晚一拍（見檔頭）
        t_end = tick - 1
        if (2 * D - 1 <= t_end < T) and (t_end - (2 * D - 1)) % D == 0:
            assert not eng_active, f"tick {tick}: 引擎還在跑就要開新批次"
            eng_active = True
            eng_s, eng_k, eng_tend, eng_buf = int(best[t_end]), 0, t_end, []

        # 3. 引擎走 2 步。批次優先，做完才輪到尾端（兩者共用同一條資料路徑）
        if eng_active:
            for _ in range(2):
                if eng_k >= 2 * D:
                    break
                if eng_k >= D:                  # 丟掉最新的 D 個，只留最舊的 D 個
                    eng_buf.append(eng_s & 1)
                eng_s = pred(mem[(eng_tend - eng_k) % MEM], eng_s)
                eng_k += 1
            if eng_k >= 2 * D:
                assert len(eng_buf) == D
                # 收集順序是 stage 由新到舊，吐出要由舊到新 -> 反轉（硬體上是 LIFO 右移）
                ready.append(list(reversed(eng_buf)))
                eng_active = False
        elif tail_active:
            for _ in range(2):
                if tail_j >= TAIL_LEN:
                    break
                tail_buf.append(tail_s & 1)
                tail_s = pred(mem[(T - 1 - tail_j) % MEM], tail_s)
                tail_j += 1
            if tail_j >= TAIL_LEN:
                ready.append(list(reversed(tail_buf)))
                tail_active = False
        elif tail_pending:
            tail_active, tail_pending = True, False
            tail_s, tail_j, tail_buf = 0, 0, []      # 終止狀態 s_T = 0

        if tick == T - 1:
            tail_pending = True         # 最後一個 stage 到了，但要等引擎空出來

        # 4. 吐出 1 個位元
        max_buf = max(max_buf, len(ready) + (1 if emitting is not None else 0))
        if emitting is None and ready:
            emitting, emit_i = ready.pop(0), 0
        if emitting is not None:
            out.append(emitting[emit_i])
            emit_i += 1
            if emit_i == len(emitting):
                emitting = None

        tick += 1

    return out, tick, max_buf


def _states(D, n_info, seed, Q=4, W=10):
    """產生一組自洽的 surv / best。

    要驗的是排程與指標算術，不是通道，所以直接餵隨機量化值就夠：原型與 golden 讀的是
    **同一份** surv / best，差別只在「什麼時候讀、讀哪個 slot、留哪一半、以什麼順序吐」。
    """
    rng = np.random.default_rng(seed)
    T = n_info + M_BITS
    rq = rng.integers(0, 1 << Q, size=(1, T, 2), dtype=np.int64)
    g = decode_fx(rq, viterbi_trellis(), Q, W, D, n_info, mode="window",
                  check_g6=False, keep_history=True)
    return g["surv"][0], g["best"][0]


def check(D, n_info, seed):
    surv, best = _states(D, n_info, seed)
    T = n_info + M_BITS
    exp = traceback(surv[None], best[None], D, n_info, M_BITS,
                    mode="batch")[0].tolist()
    got, ticks, nbuf = hw_batch(surv, best, D)

    ok_len = len(got) == T              # TB 的契約：整個 frame 恰好 T 個位元
    bad = [i for i in range(n_info) if got[i] != exp[i]]
    flush = ticks - T
    ok = ok_len and not bad and flush == 3 * D - 1 and nbuf == 2
    print(f"  {'OK  ' if ok else 'FAIL'} D={D:3d} NINFO={n_info:5d} seed={seed}"
          f"  吐出={len(got):5d}/{T}  flush={flush:4d} (3D-1={3*D-1})"
          f"  緩衝={nbuf}  不同位元={len(bad)}")
    if bad:
        print(f"       前 10 個位置 {bad[:10]}")
    return ok


def check_mem(D, n_info, mem_mult, seed=1):
    """同一個排程換記憶體深度。E-06 的獨立複驗——這次是從解碼位元端看。"""
    surv, best = _states(D, n_info, seed)
    exp = traceback(surv[None], best[None], D, n_info, M_BITS, mode="batch")[0]
    got, _, _ = hw_batch(surv, best, D, mem_mult=mem_mult)
    bad = sum(1 for i in range(n_info) if got[i] != exp[i])
    print(f"  記憶體 {mem_mult}D = {mem_mult*D:3d} slot  ->  "
          + ("沒有衝突（輸出與 golden 逐位元相同）" if not bad
             else f"**衝突**：{bad} / {n_info} 個位元不同"))
    return bad == 0


def main():
    ok = True

    print("=== 1. 逐拍排程 vs golden mode='batch' ===")
    for D in (32, 64):
        for n_info in (256, 1024):
            for seed in (1, 2, 3):
                ok &= check(D, n_info, seed)

    print("\n=== 2. 環狀緩衝深度（E-06 的獨立複驗）===")
    # 注意 2D 的失效模式：**不是全壞，是約四分之一的位元錯**——
    # 一個看起來很正常的輸出。這正是它危險的地方。
    for D in (32, 64):
        print(f"D={D}")
        ok &= (not check_mem(D, 1024, 2)) and check_mem(D, 1024, 3)

    print("\n全部通過" if ok else "\n有不符預期的結果")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
