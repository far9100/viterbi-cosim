"""ber.py — Monte Carlo BER 量測。

刻意自己寫這個迴圈（而不是套用 commsim.metrics.monte_carlo_ber），是因為量化器需要知道
該工作點的 σ，而那支 API 的 decode 參數拿不到 σ。但**統計的部分全部複用**既有模擬器：

    wilson_score_ci      二項 CI
    cluster_robust_ci    以區塊為重抽單位的 CI —— 這一支才是關鍵
    ebn0_at_target_ber   在 (Eb/N0, log10 BER) 上內插

為什麼一定要 cluster_robust_ci：Viterbi 一旦出錯就會噴出一串**相鄰**的位元錯誤。
Wilson 假設位元彼此獨立，在這裡會低估變異、把區間畫得太窄，名目 95% 的覆蓋率其實不到。
既有模擬器已經實測校準過（卷積軟判決的 var_inflation ≈ 2.03），是現成的、對的東西。
規格書要求「error count < 100 的資料點在圖上標註信賴區間」——用錯的區間就等於沒標。
"""

import hashlib
import json

import numpy as np

from .quantizer import quantize, sigma_from_ebn0
from .ref_float import commsim, decode_float
from .viterbi_fx import decode_fx


def code_rate(n_info, m):
    """終止碼率：tail bits 真的花了發射能量，所以 Eb/N0 的正規化要用這個。"""
    return n_info / (2.0 * (n_info + m))


def _run_chunk(trellis, n_info, ebn0_db, rng, B, cfg):
    """跑一批 frame，回傳 (資訊位元錯誤數, 位元數)。"""
    R = code_rate(n_info, trellis.m)
    sigma = sigma_from_ebn0(ebn0_db, R)

    info = rng.integers(0, 2, size=(B, n_info), dtype=np.uint8)
    cw = trellis.encode(info)                         # (B, T, 2)
    x = 1.0 - 2.0 * cw.astype(np.float64)             # BPSK：0 -> +1, 1 -> -1
    rx = x + rng.normal(0.0, sigma, size=x.shape)

    kind = cfg["kind"]
    if kind == "uncoded":
        # 未編碼參考：同樣的資訊位元直接 BPSK 過通道（碼率 1.0）
        sig_u = sigma_from_ebn0(ebn0_db, 1.0)
        xu = 1.0 - 2.0 * info.astype(np.float64)
        ru = xu + rng.normal(0.0, sig_u, size=xu.shape)
        dec = (ru < 0).astype(np.uint8)
    elif kind == "float":
        dec = decode_float(rx, trellis, cfg["D"], n_info,
                           mode=cfg.get("mode", "window"),
                           metric=cfg.get("metric", "soft"))
    elif kind == "fx":
        rq = quantize(rx, sigma, cfg["Q"], cfg["clip"])
        out = decode_fx(rq, trellis, cfg["Q"], cfg["W"], cfg["D"], n_info,
                        mode=cfg.get("mode", "window"),
                        check_g6=False, keep_history=False)
        dec = out["dec"]
    else:
        raise ValueError(kind)

    err = (dec != info)
    return err, err.size


def measure_ber(trellis, n_info, ebn0_db, cfg, seed,
                min_errors=200, max_bits=int(3e7), batch_frames=400):
    """跑到累積 min_errors 個位元錯誤或用完 max_bits 為止。

    回傳 dict：ber / n_errors / n_bits / ci_low / ci_high（cluster-robust）。
    """
    _, _, _, metrics = commsim()

    # 每個 (組態, SNR) 點要有自己的、**確定的**亂數串流。
    #
    # 不能用 Python 內建的 hash()：字串的 hash 在每個 process 都會被隨機加鹽
    # （PYTHONHASHSEED），所以同一個組態在不同 worker、不同次執行會拿到不同的 seed。
    # 那會讓結果無法重現——而一個無法追溯到 (seed, 組態, commit) 的 BER 點不是證據
    # （CLAUDE.md §5.3）。改用 sha256，跨 process、跨機器都是同一個值。
    key = json.dumps({"cfg": {k: str(v) for k, v in sorted(cfg.items())},
                      "ebn0": float(ebn0_db), "n_info": int(n_info)},
                     sort_keys=True)
    stream = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng([seed, stream])

    n_err = 0
    n_bits = 0
    chunk_err = []      # 每個 frame 的錯誤數 -> cluster 的重抽單位

    while n_err < min_errors and n_bits < max_bits:
        err, nb = _run_chunk(trellis, n_info, ebn0_db, rng, batch_frames, cfg)
        per_frame = err.sum(axis=1)
        chunk_err.extend(per_frame.tolist())
        n_err += int(per_frame.sum())
        n_bits += nb

    ber = n_err / n_bits if n_bits else 0.0
    # 以 frame 為 cluster：Viterbi 的錯誤在 frame 內成叢，跨 frame 才獨立。
    # cluster_robust_ci 的第二個參數是「每個 cluster 有幾個位元」的**純量**，不是陣列；
    # 回傳的是 (p_hat, ci_low, ci_high) 三個值，不是兩個。
    _, lo, hi = metrics.cluster_robust_ci(np.array(chunk_err), n_info)

    return {
        "ebn0_db": float(ebn0_db),
        "ber": float(ber),
        "n_errors": int(n_err),
        "n_bits": int(n_bits),
        "ci_low": float(lo),
        "ci_high": float(hi),
    }


def ber_curve(trellis, n_info, ebn0_list, cfg, seed, **kw):
    return [measure_ber(trellis, n_info, e, cfg, seed, **kw) for e in ebn0_list]


def _log10_sigma(ber, lo, hi):
    """由 cluster-robust CI 反推 log10(BER) 的 1-σ。CI 是 95%，故半寬 ≈ 1.96σ。

    兩個必須擋掉的邊界（低 SNR 的高 SNR 尾端真的會踩到）：
      * `lo <= 0`：錯誤數很少時 CI 下緣會壓到 0，log10 發散。改用**單邊**（上緣）估 σ。
      * `ber <= 0`：那個點根本沒量到錯誤，不能取 log，回 None 讓呼叫端丟棄它。
    回 None 而不是回一個猜出來的數——靜靜回退到預設值正是 M0 那個 SAIF timescale bug 的形狀。
    """
    if ber <= 0:
        return None
    if lo > 0 and hi > lo:
        return (np.log10(hi) - np.log10(lo)) / (2.0 * 1.96)
    if hi > ber:
        return (np.log10(hi) - np.log10(ber)) / 1.96
    return None


def required_ebn0_ci(curve, target=1e-5, n_boot=20000, seed=20260729):
    r"""`required_ebn0` 的不確定度，以參數化 bootstrap 求得。

    ## 為什麼需要這個

    `required_ebn0` 是在 (Eb/N0, log10 BER) 上做**兩點對數內插**——實測中目標 BER=1e-5
    的交叉點永遠落在 4.0/4.5 dB 這**同一個區間**內，所以每一個所報的「所需 Eb/N0」
    其實都是兩個有雜訊的 BER 點拉出來的一條弦。而 d\*、Δd\*、C1 量化損失、winner 排序
    全部建立在它上面。只給點估計、不給區間，讀者無從判斷 0.04 dB 的差是不是雜訊
    ——而實測顯示那個差**確實**是雜訊（見 `data/c1_quantization_loss.csv` 的負損失）。

    ## 為什麼是 bootstrap 而不是解析式的誤差傳播

    解析式要對 `metrics.ebn0_at_target_ber` 的內插公式做偏微分。那等於**再實作一次**
    那支函式，而兩份實作分岔時不會有任何錯誤訊息。bootstrap 直接呼叫同一支函式，
    不可能與它分岔；它也自然處理「重抽之後交叉點跳到相鄰區間」這種非線性。

    ## 可重生性

    seed 固定且與資料無關，故同一份輸入永遠得到同一個區間（`make repro` 要求逐位元組重生）。

    回傳 dict：point / sigma_db / ci_low_db / ci_high_db / n_used。
    """
    _, _, _, metrics = commsim()
    pts = [(p["ebn0_db"], p["ber"],
            _log10_sigma(p["ber"], p.get("ci_low", 0.0), p.get("ci_high", 0.0)))
           for p in curve]
    usable = [(e, b, s) for e, b, s in pts if s is not None and b > 0]
    point = required_ebn0(curve, target)
    if point is None or len(usable) < 2:
        return {"point": point, "sigma_db": None,
                "ci_low_db": None, "ci_high_db": None, "n_used": len(usable)}

    e = np.array([x[0] for x in usable])
    y = np.log10(np.array([x[1] for x in usable]))
    s = np.array([x[2] for x in usable])

    rng = np.random.default_rng(seed)
    draws = y[None, :] + rng.normal(0.0, 1.0, size=(n_boot, len(y))) * s[None, :]
    out = []
    for row in draws:
        r = metrics.ebn0_at_target_ber(e.tolist(), np.power(10.0, row).tolist(),
                                       target)
        if r is not None and np.isfinite(r):
            out.append(r)
    if len(out) < n_boot // 10:
        # 過半重抽算不出交叉點 ⇒ 這條曲線太短或太吵，不要硬給一個看起來合理的區間
        return {"point": point, "sigma_db": None,
                "ci_low_db": None, "ci_high_db": None, "n_used": len(usable)}

    out = np.array(out)
    return {"point": point,
            "sigma_db": float(out.std(ddof=1)),
            "ci_low_db": float(np.percentile(out, 2.5)),
            "ci_high_db": float(np.percentile(out, 97.5)),
            "n_used": len(usable)}


def required_ebn0(curve, target=1e-5):
    """由 BER 曲線內插出達到 target BER 所需的 Eb/N0。用既有模擬器的同一支函式。"""
    _, _, _, metrics = commsim()
    e = [p["ebn0_db"] for p in curve]
    b = [p["ber"] for p in curve]
    return metrics.ebn0_at_target_ber(e, b, target)
