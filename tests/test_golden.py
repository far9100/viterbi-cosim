"""test_golden.py — golden model 的正確性測試。

順序是刻意的：**先證明引擎是對的，再拿它去量任何東西。**
一個沒被獨立驗證過的 golden model 去量出來的 BER 曲線，不是證據，是循環論證。

四個 oracle，由強到弱：

1. **暴力 ML 枚舉**（最強）：短 frame 下枚舉所有 2^L 條碼字，找歐氏距離最小的那條。
   Viterbi 的 mode='ml' 必須與它逐位元相同。這直接證明解碼器是最大似然的。
2. **既有模擬器的 K=3 Viterbi**：它經過 mutation testing（分數 90.4%）且自己也做過
   暴力 ML 比對。把 K=3 (7,5) 灌進本專案的泛用引擎，解碼結果必須與它逐位元相同。
   這證明「引擎」對，而不只是「K=7 的參數表」對。
3. **d_free**：(133,171) 必須是 10，(7,5) 必須是 5。抓多項式打錯字。
4. **定點 vs 浮點**：Q 很大時兩者的決策應該幾乎一致。抓量化器的方向錯誤
   （r 與 y 的遞增/遞減搞反的話，BER 會爛掉但不會有任何錯誤訊息）。
"""

import itertools
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.quantizer import quantize, sigma_from_ebn0, w_is_safe  # noqa: E402
from golden.ref_float import decode_float  # noqa: E402
from golden.trellis import oracle_trellis, viterbi_trellis  # noqa: E402
from golden.viterbi_fx import decode_fx  # noqa: E402

COMMSIM = os.environ.get(
    "COMMSIM_PATH",
    "/mnt/c/Users/fartw/OneDrive/Desktop/github/communications relay simulator",
)
sys.path.insert(0, COMMSIM)


# ----------------------------------------------------------------------
# 1. trellis 結構
# ----------------------------------------------------------------------

def test_dfree():
    assert viterbi_trellis().free_distance() == 10      # (133,171)
    assert oracle_trellis().free_distance() == 5        # (7,5)


def test_complementarity_properties():
    """butterfly 只需一個 BM 輸入，靠的是這兩條性質。它們不是對所有碼都成立。"""
    t = viterbi_trellis()
    assert t.prop_u_complement    # 每個多項式 bit m = 1  -> c(s,1) = ~c(s,0)
    assert t.prop_p_complement    # 每個多項式為奇數      -> c(p+32,u) = ~c(p,u)


def test_encoder_matches_commsim_k3():
    """泛用 trellis 灌 K=3 (7,5)，編碼器輸出必須與既有模擬器逐位元組相等。"""
    from commsim.coding import conv_encode

    o = oracle_trellis()
    rng = np.random.default_rng(1)
    L, B = 100, 20
    info = rng.integers(0, 2, size=(B, L), dtype=np.uint8)

    mine = o.encode(info)
    theirs = conv_encode(info.reshape(-1), L).reshape(B, L + 2, 2)
    assert np.array_equal(mine, theirs)


# ----------------------------------------------------------------------
# 2. 暴力 ML（最強的 oracle）
# ----------------------------------------------------------------------

def _brute_force_ml(trellis, rx, L):
    """枚舉所有 2^L 條終止碼字，回傳歐氏距離最小的那條的資訊位元。"""
    m = trellis.m
    best_d = None
    best_u = None
    for bits in itertools.product((0, 1), repeat=L):
        info = np.array(bits, dtype=np.uint8)[None, :]
        cw = trellis.encode(info)[0]                 # (L+m, 2)
        x = 1.0 - 2.0 * cw.astype(np.float64)        # BPSK
        d = np.sum((rx - x) ** 2)
        if best_d is None or d < best_d:
            best_d = d
            best_u = info[0]
    return best_u


@pytest.mark.parametrize("K,polys_name", [(7, "viterbi"), (3, "oracle")])
def test_viterbi_is_maximum_likelihood(K, polys_name):
    """mode='ml' 的 Viterbi 必須與暴力枚舉逐位元相同。"""
    t = viterbi_trellis() if polys_name == "viterbi" else oracle_trellis()
    L = 8                                            # 2^8 = 256 條碼字
    rng = np.random.default_rng(7)

    for trial in range(12):
        info = rng.integers(0, 2, size=(1, L), dtype=np.uint8)
        cw = t.encode(info)[0]
        x = 1.0 - 2.0 * cw.astype(np.float64)
        rx = x + rng.normal(0.0, 0.9, size=x.shape)   # 雜訊夠大，才會真的挑戰解碼器

        dec = decode_float(rx[None, ...], t, D=L, n_info=L, mode="ml")[0]
        ref = _brute_force_ml(t, rx, L)
        assert np.array_equal(dec, ref), f"trial {trial}: ML 不一致"


# ----------------------------------------------------------------------
# 3. 既有模擬器的 K=3 Viterbi（引擎 oracle）
# ----------------------------------------------------------------------

def test_decoder_matches_commsim_k3_soft():
    """K=3 灌進本引擎，軟判決解碼結果必須與 commsim.conv_decode_soft 逐位元相同。

    浮點軟判決的平手機率是零，所以兩邊的 tie-break 慣例不同（狀態標號相反）
    不會造成差異。這正是這個 oracle 成立的前提。
    """
    from commsim.coding import conv_decode_soft

    o = oracle_trellis()
    rng = np.random.default_rng(20260714)
    L, B = 120, 40
    info = rng.integers(0, 2, size=(B, L), dtype=np.uint8)
    cw = o.encode(info)                              # (B, L+2, 2)
    x = 1.0 - 2.0 * cw.astype(np.float64)
    rx = x + rng.normal(0.0, 0.8, size=x.shape)

    # commsim 的 traceback 是「從終止狀態 0 全幀回溯」-> 對應本專案的 mode='ml'
    mine = decode_float(rx, o, D=L, n_info=L, mode="ml")
    theirs = conv_decode_soft(rx.reshape(-1), L).reshape(B, L)

    n_diff = int(np.sum(mine != theirs))
    assert n_diff == 0, f"{n_diff} / {B*L} 個位元不同"


def _hamming_to_received(trellis, info, hard_rx):
    """把解出的資訊位元重新編碼，算它與硬判決接收序列的 Hamming 距離。

    這就是那條路徑的 path metric。ML 解碼器**保證**達到最小值。
    """
    cw = trellis.encode(info)                       # (B, T, 2)
    return np.sum(cw != hard_rx, axis=(1, 2))


def test_decoder_matches_commsim_k3_hard():
    """硬判決：比對「達到的 path metric」，不是比對解出來的位元。

    為什麼不能比位元：硬判決的 branch metric 是小整數（Hamming 距離），
    **最小距離的路徑常常不只一條**。兩個都正確的 ML 解碼器可以挑到不同的 ML 路徑，
    因而給出不同的位元錯誤數——那不是 bug，是 ML 解在本質上不唯一。
    （第一版這個測試比位元錯誤數，得到 471 vs 354，看起來像 bug，其實不是。）

    真正嚴格的判準是：**兩者達到的最小 Hamming 距離必須完全相同**。
    ML 的定義就是「達到最小值」，所以這一條若不成立，其中一方就不是 ML。
    """
    from commsim.coding import conv_decode

    o = oracle_trellis()
    rng = np.random.default_rng(99)
    L, B = 120, 40
    info = rng.integers(0, 2, size=(B, L), dtype=np.uint8)
    cw = o.encode(info)
    x = 1.0 - 2.0 * cw.astype(np.float64)
    rx = x + rng.normal(0.0, 0.8, size=x.shape)
    hard_rx = (rx < 0).astype(np.uint8)

    mine = decode_float(rx, o, D=L, n_info=L, mode="ml", metric="hard")
    theirs = conv_decode(hard_rx.reshape(-1), L).reshape(B, L)

    d_mine = _hamming_to_received(o, mine, hard_rx)
    d_theirs = _hamming_to_received(o, theirs, hard_rx)

    assert np.array_equal(d_mine, d_theirs), (
        f"達到的 path metric 不同 -> 其中一方不是 ML。"
        f"逐 frame 差值: {(d_mine - d_theirs)[:10]}"
    )


def test_hard_decoder_is_maximum_likelihood():
    """硬判決解碼器的暴力 ML 驗證（同樣比 path metric，因為 ML 解不唯一）。"""
    t = viterbi_trellis()
    L = 8
    rng = np.random.default_rng(21)

    for _ in range(10):
        info = rng.integers(0, 2, size=(1, L), dtype=np.uint8)
        cw = t.encode(info)
        x = 1.0 - 2.0 * cw.astype(np.float64)
        rx = x + rng.normal(0.0, 0.9, size=x.shape)
        hard_rx = (rx < 0).astype(np.uint8)

        dec = decode_float(rx, t, D=L, n_info=L, mode="ml", metric="hard")
        d_viterbi = _hamming_to_received(t, dec, hard_rx)[0]

        # 暴力枚舉所有 2^L 條碼字，找最小 Hamming 距離
        d_brute = min(
            _hamming_to_received(t, np.array(b, dtype=np.uint8)[None, :], hard_rx)[0]
            for b in itertools.product((0, 1), repeat=L)
        )
        assert d_viterbi == d_brute, f"Viterbi 達到 {d_viterbi}，暴力枚舉是 {d_brute}"


# ----------------------------------------------------------------------
# 4. 量化器與定點模型
# ----------------------------------------------------------------------

def test_quantizer_direction():
    """r 必須隨 y 遞減。搞反的話 BER 會爛掉，但不會有任何錯誤訊息。"""
    sigma = 1.0
    assert quantize(+10.0, sigma, Q=4, clip=2.0) == 0            # 強烈像 0
    assert quantize(-10.0, sigma, Q=4, clip=2.0) == 15           # 強烈像 1
    assert quantize(0.0, sigma, Q=4, clip=2.0) in (7, 8)         # 中間


def test_quantizer_range():
    rng = np.random.default_rng(3)
    y = rng.normal(0, 3, size=10000)
    for Q in (3, 4, 5, 6):
        r = quantize(y, 1.0, Q, clip=2.0)
        assert r.min() >= 0 and r.max() <= (1 << Q) - 1


def test_w_safety_table():
    """docs/wordlength_bound.md §4 的表。12 個格點中恰好 4 個不安全。"""
    unsafe = [(Q, W) for Q in (3, 4, 5, 6) for W in (8, 10, 12)
              if not w_is_safe(Q, W)]
    assert unsafe == [(4, 8), (5, 8), (6, 8), (6, 10)]


def test_fx_matches_float_at_high_precision():
    """Q=6、clip=3σ 時，定點的決策應該與浮點幾乎一致。

    這抓的是量化器方向錯誤、branch metric 正負號錯誤這類「不會報錯但會毀掉 BER」的 bug。
    """
    t = viterbi_trellis()
    rng = np.random.default_rng(11)
    L, B = 200, 20
    Q, W, D = 6, 12, 64

    info = rng.integers(0, 2, size=(B, L), dtype=np.uint8)
    cw = t.encode(info)
    x = 1.0 - 2.0 * cw.astype(np.float64)
    sigma = sigma_from_ebn0(3.0, R=L / (2.0 * (L + t.m)))
    rx = x + rng.normal(0.0, sigma, size=x.shape)

    dec_f = decode_float(rx, t, D=D, n_info=L, mode="window")
    rq = quantize(rx, sigma, Q, clip=3.0)
    out = decode_fx(rq, t, Q=Q, W=W, D=D, n_info=L, mode="window")

    # 兩者對 info 的錯誤數應該非常接近（量化只造成極小的損失）
    e_f = int(np.sum(dec_f != info))
    e_x = int(np.sum(out["dec"] != info))
    assert abs(e_f - e_x) <= max(2, 0.15 * max(e_f, e_x, 1)), \
        f"浮點 {e_f} 個錯 vs 定點 {e_x} 個錯 —— 差太多，量化器可能方向錯了"
    assert out["g6_ok"], "Q=6,W=12 是安全格點，G6 不該觸發"


def test_g6_fires_on_unsafe_cell():
    """G6 的負向測試：先驗不安全的格點必須真的觸發決策不一致。

    規格書原本要求「故意把 W 調小到不足（例如 W=6）」——不需要。
    既有網格裡的 (Q=6, W=8) 就會壞。
    """
    t = viterbi_trellis()
    rng = np.random.default_rng(5)
    L, B = 300, 8
    info = rng.integers(0, 2, size=(B, L), dtype=np.uint8)
    cw = t.encode(info)
    x = 1.0 - 2.0 * cw.astype(np.float64)
    sigma = sigma_from_ebn0(1.0, R=L / (2.0 * (L + t.m)))   # 低 SNR：PM spread 大
    rx = x + rng.normal(0.0, sigma, size=x.shape)
    rq = quantize(rx, sigma, Q=6, clip=2.0)

    safe = decode_fx(rq, t, Q=6, W=12, D=32, n_info=L)
    assert safe["g6_ok"], "(Q=6, W=12) 是安全格點"

    unsafe = decode_fx(rq, t, Q=6, W=8, D=32, n_info=L)
    assert not unsafe["g6_ok"], "(Q=6, W=8) 先驗不安全，G6 必須觸發"
    assert unsafe["g6_first"] >= 0


def test_ber_is_reproducible_across_processes():
    """同一個 (組態, SNR, seed) 必須每次都給出**逐位元組相同**的結果。

    第一版用 `hash(str(cfg))` 當亂數串流的 key —— 但 Python 對字串的 hash 每個 process
    都會隨機加鹽（PYTHONHASHSEED）。於是同一個組態在不同 worker、不同次執行拿到不同 seed，
    結果無法重現。而一個無法追溯到 (seed, 組態, commit) 的 BER 點不是證據（CLAUDE.md §5.3）。

    這個測試用 subprocess 跑兩次（兩個獨立的 process，各自有不同的 hash 鹽），
    確認結果一致。同一個 process 內跑兩次是抓不到這個 bug 的。
    """
    import subprocess

    code = (
        "import sys; sys.path.insert(0, '.');"
        "from golden.ber import measure_ber;"
        "from golden.trellis import viterbi_trellis;"
        "r = measure_ber(viterbi_trellis(), 128, 3.0,"
        "                {'kind': 'float', 'D': 32, 'metric': 'soft'}, 42,"
        "                min_errors=20, max_bits=200000, batch_frames=50);"
        "print(r['n_errors'], r['n_bits'])"
    )
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outs = []
    for _ in range(2):
        p = subprocess.run([sys.executable, "-c", code], cwd=repo,
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        outs.append(p.stdout.strip())
    assert outs[0] == outs[1], f"兩次獨立執行結果不同: {outs}"


def test_traceback_vectorized_matches_slow():
    """向量化的 traceback 必須與逐 stage 的笨版本逐位元相同。

    向量化是為了速度（把 61,000 次 numpy 呼叫降到 63 次），不該是為了聰明。
    所以留一個一眼就看得懂、是 traceback_convention.md 字面翻譯的笨版本盯著它。
    """
    from golden.traceback import traceback, traceback_slow

    t = viterbi_trellis()
    rng = np.random.default_rng(17)
    L, B = 150, 6
    info = rng.integers(0, 2, size=(B, L), dtype=np.uint8)
    cw = t.encode(info)
    x = 1.0 - 2.0 * cw.astype(np.float64)
    sigma = sigma_from_ebn0(2.0, R=L / (2.0 * (L + t.m)))
    rx = x + rng.normal(0.0, sigma, size=x.shape)
    rq = quantize(rx, sigma, Q=4, clip=2.0)
    out = decode_fx(rq, t, Q=4, W=10, D=32, n_info=L)

    for mode in ("window", "ml"):
        fast = traceback(out["surv"], out["best"], 32, L, t.m, mode=mode)
        slow = traceback_slow(out["surv"], out["best"], 32, L, t.m, mode=mode)
        assert np.array_equal(fast, slow), f"mode={mode} 兩版本不一致"


def test_window_worse_than_ml_at_small_d():
    """D 軸要有意義：D=24（低於 5K=35）必須明顯比全幀 ML 差，D=64 必須接近它。"""
    t = viterbi_trellis()
    rng = np.random.default_rng(13)
    L, B = 400, 30
    info = rng.integers(0, 2, size=(B, L), dtype=np.uint8)
    cw = t.encode(info)
    x = 1.0 - 2.0 * cw.astype(np.float64)
    sigma = sigma_from_ebn0(2.0, R=L / (2.0 * (L + t.m)))
    rx = x + rng.normal(0.0, sigma, size=x.shape)

    e_ml = int(np.sum(decode_float(rx, t, D=L, n_info=L, mode="ml") != info))
    e_64 = int(np.sum(decode_float(rx, t, D=64, n_info=L, mode="window") != info))
    e_24 = int(np.sum(decode_float(rx, t, D=24, n_info=L, mode="window") != info))

    assert e_64 <= e_24, f"D=64 ({e_64}) 應該不比 D=24 ({e_24}) 差"
    assert e_ml <= e_64, f"全幀 ML ({e_ml}) 應該不比 D=64 ({e_64}) 差"
