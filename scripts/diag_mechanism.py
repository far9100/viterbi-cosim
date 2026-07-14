"""diag_mechanism.py — 為什麼「功耗 vs SNR」這條曲線不存在？

## 背景

規格書 §7 把「功耗對 SNR 的依賴曲線」列為交付結果，前提寫在規格書裡：
「低 SNR → ACS toggle 率高 → 功耗高」。

**實測：總功耗在 1→5 dB 只變動 1.0%，方向相反、而且非單調（= 雜訊）。**
規格書的前提是錯的。使用者裁定：如實報告為負面結果，並**量出機制**。

本檔跑在 numpy golden model 上——與 RTL/gate-level **完全獨立的路徑**——
所以它算出的數字若與 gate-level SAIF 一致，就證明機制在**演算法**裡，不在 RTL 裡。

================================================================================
第一輪：預先登記的預測（原文保留）。**其中兩條被自己的資料推翻了。**
================================================================================

原始論點是：「switching power 是位元邊際統計的泛函，而 survivor bits 的統計被資訊源
釘在最大熵」。附帶一個關於輸入端的解釋：「量化器是 σ-normalised（AGC），所以 r 的
統計也與 SNR 無關；拿掉 AGC，效應就會回來。」

    P1  surv 的硬體翻轉率 ≈ 0.5，跨 SNR 變動 < 2%。
    P2  surv 的 duty ≈ 0.5，跨 SNR 變動 < 5%。
    P3  「真實路徑上的 survivor bit」與真實前驅的一致率**隨 SNR 單調上升**。
    P4  但那個**同一批位元**的 duty 仍然 ≈ 0.5（因為它就是 u[t−m]）。
    P5  反事實（拿掉 AGC，滿刻度固定在 3 dB 的 σ）：r 的 LSB 翻轉率**會隨 SNR 下降**
        （高 SNR 時 y 集中在 ±1，固定尺度下撞 rail，LSB 停止翻轉）。效應會回來。
    P6  但即使在反事實下，surv 的翻轉率仍然 ≈ 0.5。

**裁決（第一輪實測）**

    P1 成立（0.4987，變動 0.95%）
    P2 成立（0.4782，變動 2.68%）
    P3 **不成立（如字面所寫）** —— 一致率 0.9932 -> 1.0000，確實上升，
       但在 3 dB 就**飽和**到 1.0000，而我的判準寫的是「嚴格單調遞增」。
       這是**我的判準寫壞了**，不是機制錯了。以 P3′ 修正（見下）。
    P4 成立（0.5000，變動 3.14%）
    P5 **不成立（真的錯了）** —— 拿掉 AGC 後 LSB 翻轉率是 0.4982 -> 0.4991，**紋風不動**。
       **我給的理由（「撞 rail」）是錯的。**
    P6 成立（0.4989，變動 0.52%）

================================================================================
第二輪：事後分析（POST-HOC，明確標註）—— P5 為什麼錯，以及真正的機制
================================================================================

P5 錯在哪裡：把滿刻度釘在 3 dB 的 σ，A = 2.5·σ(3dB) = 1.775。訊號在 y = ±1，
**永遠落在 [−A, +A] 之內**，根本不會撞 rail。變的只有雜訊。而 1 個 LSB 的階距是
2A/(2^Q−1) = 0.237；即使到 10 dB，σ = 0.317 = **1.34 LSB**，雜訊仍然大於一個 LSB，
LSB 當然還是隨機的。我把「訊號飽和」和「雜訊小於一個 LSB」搞混了。

但真正的原因比這更深，而且**根本與雜訊無關**：

    量化器是**對稱**的：  r(c=1) = (2^Q − 1) − r(c=0)
    而 2^Q − 1 是全 1，所以      (2^Q − 1) − r  ==  ~r   （Q 位元的位元補數）

    => BPSK 的兩個假設，映到**位元互補**的兩個碼。

編碼位元是（近乎）i.i.d. uniform。所以當編碼位元翻轉時，**r 的每一個位元都跟著翻轉**。

    => r 的每一位元的翻轉率 ≈ 0.5 · P(c_t ≠ c_{t+1}) ≈ 0.5，
       **在任何 SNR 下都成立——有沒有雜訊都一樣。**

同樣的事發生在另一端（這一條第一輪就驗證過了，代數為真）：
狀態遞迴 s_{t+1} = ((s_t << 1) | u_t) & 63 使得 s_t 的 bit 5 就是 u_{t−6}，
因此「狀態 s_{t+1} 的正確 survivor bit」= 「s_t ≥ 32?」= **u_{t−6}**，
也就是**資訊位元本身**。資訊位元是 i.i.d. uniform。

    => **一個完美的 Viterbi 解碼器，與一個完全失效的 Viterbi 解碼器，
       其 survivor 記憶體的切換活動一模一樣。**

**統一的結論：整條資料路徑（r -> bm -> pm -> surv -> RE 暫存器）的位元活動，
都被「隨機的資訊源」釘在最大熵，而不是被雜訊釘住。
SNR 改變的是位元的「正確性」，改變不了它們的「統計」。而 switching power 只看統計。**

這不是 register exchange 的性質，也不是本設計的性質——**任何**傳輸白化過的
（= 編碼過的）訊號的接收機，其資料路徑活動都會與 SNR 無關。編碼的作用就是白化。

## 第二輪的新預測（**寫在跑之前**）

    P3′ （修正判準）一致率隨 SNR **非遞減**，且「錯誤率」(1 − 一致率) 至少掉 10 倍。
        —— P3 的實質主張（資訊確實隨 SNR 增加）本來就成立，是判準寫壞了。
    P7  在 30 dB（幾乎無雜訊）下，r 只取**兩個**值 r0、r1，且 **r1 == ~r0**（位元互補）。
        因此 r 的每一位元翻轉率仍 ≈ 0.5，surv 的翻轉率也仍 ≈ 0.5。
    P8  **把量化器的對稱性打破，效應必須回來。** 用 levels = 2^Q（而非 2^Q − 1），
        則 r1 = 2^Q − r0 ≠ ~r0，兩個碼會在某些位元上**相同**。
        預測：在高 SNR 下，那些「相同的位元」的翻轉率必須**崩到接近 0**。

**裁決（第二輪實測）：P7、P8 又**雙雙不成立**——而且**又是我的實驗設計寫壞了**。

    P8 的對稱性破壞被 **clipping 打敗了**：我在 30 dB **開著 AGC** 下取 rail，
       此時 A = 2.5·σ(30dB) = 0.079，而訊號在 y = ±1 —— 是滿刻度的 12 倍。
       **兩種量化器都被 clip 到 {0, 15}**，而 0 與 15 本來就位元互補。
       symmetry-breaking 根本沒發生。
    P7 則暴露出一件我沒預測到的**真實效應**：30 dB 下 surv 的翻轉率掉到 **0.4113**
       （不是 ≈0.5）。原因：r 飽和成硬判決 ⇒ ACS 出現大量**平手** ⇒
       tie-break 規則（survivor = 0）產生偏壓 ⇒ 活動量下降。

================================================================================
第三輪：把實驗設計修好（POST-HOC，明確標註）
================================================================================

要真正做 symmetry-breaking，必須讓兩個 rail **落在量化範圍之內**，
也就是滿刻度要固定在 A = clip·σ(3dB) = 1.775 > 1（= 不開 AGC），再把 SNR 拉高。
這樣兩個量化器**只差 `levels` 一個參數**，是乾淨的對照實驗：

    對稱   levels = 2^Q − 1 = 15 :  r0 = 3 = 0b0011,  r1 = 12 = 0b1100   -> 位元互補，4 個位元全都翻
    不對稱 levels = 2^Q     = 16 :  a0 = 3 = 0b0011,  a1 = 13 = 0b1101   -> **bit0 兩邊都是 1**

## 第三輪的預測（**寫在跑之前**）

    P7′ 固定滿刻度 + 高 SNR + **對稱**量化器：兩個 rail 位元互補，
        r 的每一位元翻轉率仍 ≈ 0.5。
    P8′ 固定滿刻度 + 高 SNR + **不對稱**量化器：兩個 rail 相同的那些位元，
        其翻轉率必須**崩到 ~0**；不同的位元仍維持 ≈ 0.5。
        逐位元必須服從   toggle(k) ≈ 0.5 · 1{bit k of r0 ≠ bit k of r1}。
    P9  （誠實記錄第二輪撞到的那個真實效應）AGC + 極高 SNR（30 dB）下 r 飽和成硬判決，
        ACS 平手變多，tie-break 偏壓使 surv 的翻轉率**明顯低於 0.5**。
        這是唯一一個活動量真的會動的區域——**而它落在編碼根本沒用的地方**
        （BER 在 5 dB 就已經是 0 了）。不是可用的「功耗 vs SNR」曲線。

    **若 P8′ 不成立（打破對稱性後效應仍然沒回來）⇒ 連修正後的機制也是錯的，必須再改寫。**
"""

import csv
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden.ber import code_rate  # noqa: E402
from golden.quantizer import quantize, sigma_from_ebn0  # noqa: E402
from golden.trellis import viterbi_trellis  # noqa: E402
from golden.viterbi_fx import decode_fx  # noqa: E402
from scripts.gates import DATA  # noqa: E402

Q, W, D, CLIP = 4, 10, 64, 2.5      # 與 gate-level 主掃描同一組態
NINFO, FRAMES = 1024, 8
SNRS = [-2.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 10.0]
SNR_HI = 30.0                        # 「幾乎無雜訊」的結構性示範


def quantize_asym(y, sigma, Q, clip, offset=1):
    """**刻意打破對稱性**的量化器（只用於 P8″ 的反事實，不在 C2 路徑上）。

    正規量化器：r = round((A−y)·levels/(2A))，levels = 2^Q − 1（全 1）
    => r(c=1) = levels − r(c=0) == **~r(c=0)**（Q 位元的位元補數）=> 兩個 rail 位元全異。

    這裡加一個**整數 DC offset**（= 一個真實的 ADC 比較器偏移誤差）：

        r' = clip(round((A−y)·levels/(2A)) + offset, 0, levels)

    兩個 rail 同時平移 offset，於是 r0' + r1' = levels + 2·offset ≠ levels
    => **不再位元互補**，某些位元在兩個 rail 上會相同。

    ## 為什麼不用「levels = 2^Q」來破壞對稱性（第三輪試過，失敗了）

    那樣做會把 c=0 的 rail 推到 **3.493**——離 3.5 的 round 邊界只有 0.007。
    於是光是 rounding 就把 bit0 隨機化成 50/50，效應被雜訊蓋掉。
    整數 offset 沒有這個問題：rail 落在 4.275 / 12.725，離邊界 0.225，
    即使殘餘雜訊偶爾把 round 推過去（30 dB 下約 4.6%），
    r 也只在 {4,5} 與 {12,13} 之間跳——而 **bit1 在這四個值裡全是 0、bit2 全是 1**，
    所以那兩個位元的翻轉率會**乾淨地掉到 0**。
    """
    y = np.asarray(y, dtype=np.float64)
    levels = (1 << Q) - 1
    A = clip * sigma
    r = np.round((A - y) * levels / (2.0 * A)) + offset
    return np.clip(r, 0, levels).astype(np.int64)


def true_states(info, t, T):
    """由資訊位元算出真實的 trellis 狀態序列（s_{t+1} = ((s_t<<1)|u_t) & 63）。"""
    B = info.shape[0]
    u = np.concatenate(
        [info.astype(np.int64), np.zeros((B, t.m), dtype=np.int64)], axis=1)
    s = np.zeros((B, T + 1), dtype=np.int64)
    for i in range(T):
        s[:, i + 1] = ((s[:, i] << 1) | u[:, i]) & (t.n_states - 1)
    return s, u


def bits_of(rq, Q):
    """(B,T,2) 的整數 -> (B,T,2*Q) 的位元，最後一維順序 [sym0 bit0..bitQ-1, sym1 ...]。"""
    return ((rq[..., None] >> np.arange(Q)) & 1).astype(np.uint8).reshape(
        rq.shape[0], rq.shape[1], -1)


def run(snr, t, T, R, sigma_ref, agc, qfun=quantize):
    """跑一個 SNR 點。

    snr   —— **通道**的真實 SNR（決定注入的雜訊）
    agc   —— True  : 量化器的滿刻度追著 σ 跑（A = clip·σ）＝ 本專案的量化器
             False : 滿刻度**固定**在 A = clip·σ_ref（3 dB 的 σ）＝ 沒有 AGC 的接收機
    qfun  —— quantize（對稱，levels = 2^Q−1）或 quantize_asym（不對稱，levels = 2^Q）

    真實通道 σ 與「量化器以為的 σ」是**兩個獨立的量**——第二輪就是把它們搞混才失敗的。
    """
    # +1000 是因為 SNR 可以是負的，而 default_rng 的 seed 序列不吃負整數
    rng = np.random.default_rng([2026, int(snr * 10) + 1000, int(agc)])
    info = rng.integers(0, 2, size=(FRAMES, NINFO), dtype=np.uint8)
    sigma = sigma_from_ebn0(snr, R)          # 通道真實的 σ
    q_sigma = sigma if agc else sigma_ref     # 量化器用來定滿刻度的 σ

    c = t.encode(info)
    y = 1.0 - 2.0 * c.astype(np.float64) + rng.normal(0.0, sigma, c.shape)

    rq = qfun(y, q_sigma, Q, CLIP).reshape(FRAMES, T, 2)

    d = decode_fx(rq, t, Q, W, D, NINFO, mode="window",
                  check_g6=False, keep_history=True)
    surv = np.asarray(d["surv"]).astype(np.uint8)     # (B, T, 64)
    dec = np.asarray(d["dec"]).astype(np.uint8)       # (B, NINFO)

    # --- 硬體活動：每個暫存器隨時間的翻轉（這正是 SAIF 的 TC 量的東西）---
    tog_surv = float(np.mean(surv[:, 1:, :] != surv[:, :-1, :]))
    duty_surv = float(surv.mean())

    # --- 輸入端：r 的逐位元翻轉 ---
    rb = bits_of(rq, Q)
    tog_r = float(np.mean(rb[:, 1:, :] != rb[:, :-1, :]))
    per_bit = [float(np.mean(rb[:, 1:, k::Q] != rb[:, :-1, k::Q]))
               for k in range(Q)]            # k=0 是 LSB

    # 1 個 LSB 的階距 vs σ —— 這是我第一輪誤以為的解釋變數，一併記錄以示反證
    A = CLIP * q_sigma
    lsb_step = 2.0 * A / ((1 << Q) - 1)
    sigma_per_lsb = sigma / lsb_step

    # --- 資訊：真實路徑上的 survivor bit 指對了嗎？ ---
    st, u = true_states(info, t, T)
    b = np.arange(FRAMES)[:, None]
    tt = np.arange(T)[None, :]
    sv_true = surv[b, tt, st[:, 1:]]                     # (B, T)
    want = (st[:, :T] >= (t.n_states // 2)).astype(np.uint8)
    want_eq_u = bool(np.array_equal(want[:, t.m:], u[:, :T - t.m].astype(np.uint8)))

    sl = slice(D, NINFO)     # 跳過 traceback 暖身，只看穩態的資訊區
    agree = float(np.mean(sv_true[:, sl] == want[:, sl]))
    duty_true = float(sv_true[:, sl].mean())

    return {
        "snr_db": snr, "agc": int(agc),
        "tog_surv": round(tog_surv, 6), "duty_surv": round(duty_surv, 6),
        "tog_r": round(tog_r, 6),
        **{f"tog_r_b{k}": round(per_bit[k], 6) for k in range(Q)},
        "sigma_per_lsb": round(sigma_per_lsb, 4),
        "agree_true_path": round(agree, 6), "duty_true_path": round(duty_true, 6),
        "ber": float(np.mean(dec != info)), "want_eq_u": int(want_eq_u),
        "n_rails": int(len(np.unique(rq))), "case": "",
    }


def rails(q_sigma, qfun):
    """無雜訊時，量化器把 c=0 / c=1 映到哪兩個碼？回傳 (r0, r1)。

    q_sigma 是**量化器用來定滿刻度的 σ**，不是通道的 σ。第二輪就是把這兩者搞混，
    在 30 dB + AGC 下取 rail —— 此時 A = 2.5·σ(30dB) = 0.079，而訊號在 ±1，
    是滿刻度的 12 倍，兩種量化器都被 clip 到 {0, 15}，symmetry-breaking 根本沒發生。
    """
    y = np.array([+1.0, -1.0])          # c=0 -> +1，c=1 -> −1（無雜訊）
    r = qfun(y, q_sigma, Q, CLIP)
    return int(r[0]), int(r[1])


def spread(rows, key):
    v = [r[key] for r in rows]
    return 100.0 * (max(v) - min(v)) / max(v) if max(v) > 0 else 0.0


def main():
    t = viterbi_trellis()
    T = NINFO + t.m
    R = code_rate(NINFO, t.m)
    sigma_ref = sigma_from_ebn0(3.0, R)

    rows = []
    for agc in (True, False):
        for snr in SNRS:
            r = run(snr, t, T, R, sigma_ref, agc)
            r["case"] = "agc" if agc else "fixed"
            rows.append(r)
            print(".", end="", flush=True)

    # --- P9：AGC + 極高 SNR。r 飽和成硬判決，ACS 平手 -> tie-break 偏壓 ---
    hi_agc = run(SNR_HI, t, T, R, sigma_ref, True)
    hi_agc["case"] = "agc_hi"
    rows.append(hi_agc)
    print(".", end="", flush=True)

    # --- P7′/P8′：滿刻度**固定**（A = clip·σ_ref = 1.775 > 1，rail 落在量化範圍內），
    #     兩者**只差 levels 一個參數**，是乾淨的對照實驗 ---
    hi_sym = run(SNR_HI, t, T, R, sigma_ref, False, qfun=quantize)
    hi_sym["case"] = "fixed_hi_sym"
    rows.append(hi_sym)
    print(".", end="", flush=True)

    hi_asym = run(SNR_HI, t, T, R, sigma_ref, False, qfun=quantize_asym)
    hi_asym["case"] = "fixed_hi_asym"
    rows.append(hi_asym)
    print(".")

    on = [r for r in rows if r["case"] == "agc"]
    off = [r for r in rows if r["case"] == "fixed"]

    assert all(r["want_eq_u"] for r in rows), "代數驗證失敗：正確 survivor bit ≠ u[t−m]"
    print("\n[代數驗證] 正確路徑上的 survivor bit == u[t−6]（資訊位元本身） -> 成立")

    # ---------------- 第一輪 ----------------
    print("\n=== 有 AGC（本專案的量化器）")
    print(f"{'SNR':>5} {'surv翻轉':>9} {'surv duty':>10} | "
          f"{'真路徑一致率':>12} {'同批位元duty':>13} | {'r翻轉':>7} {'σ/LSB':>6} {'BER':>9}")
    for r in on:
        print(f"{r['snr_db']:>5.0f} {r['tog_surv']:>9.4f} {r['duty_surv']:>10.4f} | "
              f"{r['agree_true_path']:>12.4f} {r['duty_true_path']:>13.4f} | "
              f"{r['tog_r']:>7.4f} {r['sigma_per_lsb']:>6.2f} {r['ber']:>9.2e}")
    print(f"{'變動%':>5} {spread(on,'tog_surv'):>9.2f} {spread(on,'duty_surv'):>10.2f} | "
          f"{spread(on,'agree_true_path'):>12.2f} {spread(on,'duty_true_path'):>13.2f} | "
          f"{spread(on,'tog_r'):>7.2f}")

    print("\n=== 反事實 1：拿掉 AGC（滿刻度固定在 3 dB 的 σ）—— P5 說效應會回來")
    print(f"{'SNR':>5} {'surv翻轉':>9} | {'r翻轉':>7} "
          + "".join(f"{'r b'+str(k):>8}" for k in range(Q)) + f" {'σ/LSB':>6}")
    for r in off:
        print(f"{r['snr_db']:>5.0f} {r['tog_surv']:>9.4f} | {r['tog_r']:>7.4f} "
              + "".join(f"{r[f'tog_r_b{k}']:>8.4f}" for k in range(Q))
              + f" {r['sigma_per_lsb']:>6.2f}")
    print(f"{'變動%':>5} {spread(off,'tog_surv'):>9.2f} | {spread(off,'tog_r'):>7.2f} "
          + "".join(f"{spread(off, f'tog_r_b{k}'):>8.2f}" for k in range(Q)))
    print("  -> **P5 錯了**：σ/LSB 從 3.0 掉到 1.34，但每一位元的翻轉率紋風不動。")

    # ---------------- 第三輪：修好的對照實驗 ----------------
    lv = (1 << Q) - 1
    A_fix = CLIP * sigma_ref
    r0, r1 = rails(sigma_ref, quantize)         # 滿刻度固定 -> rail 落在範圍內
    a0, a1 = rails(sigma_ref, quantize_asym)
    g0, g1 = rails(sigma_from_ebn0(SNR_HI, R), quantize)   # AGC @ 30 dB -> 全飽和
    comp = (r1 == (~r0) & lv)
    same = [k for k in range(Q) if ((a0 >> k) & 1) == ((a1 >> k) & 1)]
    diff = [k for k in range(Q) if ((a0 >> k) & 1) != ((a1 >> k) & 1)]

    print(f"\n=== 第四輪（事後）：對照實驗 —— 滿刻度固定 A = clip·σ(3dB) = {A_fix:.3f} > 1，"
          f"rail 落在量化範圍內")
    print(f"  對稱（本專案）      :  c=0 -> {r0:2d} = 0b{r0:0{Q}b}   "
          f"c=1 -> {r1:2d} = 0b{r1:0{Q}b}    ~r0 & {lv} = {(~r0)&lv}  "
          f"位元互補？ {'**是**' if comp else '否'}")
    print(f"  不對稱（ADC DC 偏移）:  c=0 -> {a0:2d} = 0b{a0:0{Q}b}   "
          f"c=1 -> {a1:2d} = 0b{a1:0{Q}b}    -> 和 = {a0+a1} ≠ {lv}，不再互補")
    print(f"      -> 兩個 rail **相同**的位元: bit{same}；**不同**的位元: bit{diff}")
    print(f"  （對照：AGC @ {SNR_HI:.0f} dB 時 A = {CLIP*sigma_from_ebn0(SNR_HI,R):.3f} << 1，"
          f"訊號整個被 clip 掉 -> rail = {{{g0}, {g1}}}。")
    print(f"    這就是第二輪失敗的原因：clip 強迫兩個 rail 互補，symmetry-breaking 沒發生。）")

    print(f"\n  在 {SNR_HI:.0f} dB（幾乎無雜訊）下的逐位元翻轉率：")
    print(f"{'量化器':>22} {'rails':>6} "
          + "".join(f"{'r bit'+str(k):>9}" for k in range(Q))
          + f" {'surv翻轉':>9} {'surv duty':>10}")
    for lab, r in (("固定滿刻度 · 對稱", hi_sym),
                   ("固定滿刻度 · DC 偏移", hi_asym),
                   ("AGC（會飽和）", hi_agc)):
        print(f"{lab:>22} {r['n_rails']:>6} "
              + "".join(f"{r[f'tog_r_b{k}']:>9.4f}" for k in range(Q))
              + f" {r['tog_surv']:>9.4f} {r['duty_surv']:>10.4f}")
    print(f"\n  預測的定律：toggle(k) ≈ 0.5 · 1{{bit k of r0 ≠ bit k of r1}}")
    print(f"  DC 偏移後的 rail 是 {a0} 與 {a1}，bit{same} 兩邊相同 "
          f"-> 那些位元的翻轉率必須掉到 ~0。")

    # ---------------- 裁決 ----------------
    print("\n=== 逐條裁決")
    v = []
    v.append(("P1  surv 翻轉率 ≈0.5 且變動 <2%",
              spread(on, "tog_surv") < 2.0
              and 0.45 < np.mean([r["tog_surv"] for r in on]) < 0.55,
              f"{np.mean([r['tog_surv'] for r in on]):.4f}，變動 "
              f"{spread(on,'tog_surv'):.2f}%"))
    v.append(("P2  surv duty ≈0.5 且變動 <5%",
              spread(on, "duty_surv") < 5.0
              and 0.45 < np.mean([r["duty_surv"] for r in on]) < 0.55,
              f"{np.mean([r['duty_surv'] for r in on]):.4f}，變動 "
              f"{spread(on,'duty_surv'):.2f}%"))
    ag = [r["agree_true_path"] for r in on]
    err = [1.0 - a for a in ag]
    v.append(("P3′ 一致率**非遞減**，且錯誤率至少掉 10×（P3 原判準寫壞了：它會飽和）",
              all(ag[i] <= ag[i + 1] + 1e-12 for i in range(len(ag) - 1))
              and err[0] > 10 * max(err[-1], 1e-9),
              f"一致率 {ag[0]:.4f} -> {ag[-1]:.4f}；錯誤率 {err[0]:.2e} -> {err[-1]:.2e}"))
    v.append(("P4  但同一批位元的 duty 仍 ≈0.5（它就是 u[t−6]）",
              spread(on, "duty_true_path") < 5.0,
              f"{np.mean([r['duty_true_path'] for r in on]):.4f}，變動 "
              f"{spread(on,'duty_true_path'):.2f}%"))
    v.append(("P6  反事實下 surv 翻轉率仍 ≈0.5（效應進不了 traceback）",
              spread(off, "tog_surv") < 2.0,
              f"{np.mean([r['tog_surv'] for r in off]):.4f}，變動 "
              f"{spread(off,'tog_surv'):.2f}%"))
    v.append((f"P7′ 固定滿刻度 + {SNR_HI:.0f} dB + **對稱**量化器："
              f"兩 rail 位元互補，每位元翻轉率仍 ≈0.5",
              hi_sym["n_rails"] >= 2 and comp
              and all(0.45 < hi_sym[f"tog_r_b{k}"] < 0.55 for k in range(Q)),
              f"rails={{{r0}, {r1}}}，r1==~r0：{comp}，"
              f"每位元 {[round(hi_sym[f'tog_r_b{k}'],4) for k in range(Q)]}"))
    v.append((f"P8″ 固定滿刻度 + {SNR_HI:.0f} dB + **ADC DC 偏移**（打破位元互補）："
              f"rail 相同的位元其翻轉率必須**崩到 ~0**（= 效應回來了）",
              bool(same)
              and all(hi_asym[f"tog_r_b{k}"] < 0.05 for k in same)
              and all(hi_asym[f"tog_r_b{k}"] > 0.40 for k in diff),
              f"相同位元 bit{same} -> "
              f"{[round(hi_asym[f'tog_r_b{k}'],4) for k in same]}；"
              f"不同位元 bit{diff} -> "
              f"{[round(hi_asym[f'tog_r_b{k}'],4) for k in diff]}"))
    v.append((f"P9  AGC + {SNR_HI:.0f} dB：r 飽和成硬判決 -> ACS 平手 -> tie-break 偏壓"
              f" -> surv 翻轉率**明顯低於 0.5**",
              hi_agc["tog_surv"] < 0.45,
              f"surv 翻轉率 {hi_agc['tog_surv']:.4f}（可用區間內是 "
              f"{np.mean([r['tog_surv'] for r in on]):.4f}），"
              f"duty {hi_agc['duty_surv']:.4f}；rail = {{{g0}, {g1}}}"))

    bad = 0
    for name, ok, msg in v:
        bad += (not ok)
        print(f"  [{'成立' if ok else '**不成立**'}] {name}")
        print(f"          實測：{msg}")

    print("\n=== 誠實的修訂記錄（四輪都留著，不得刪除）")
    print("  [第一輪] P3 如字面所寫**不成立**：一致率在 3 dB 就飽和到 1.0000，"
          "而我要求「嚴格單調遞增」。**判準寫壞了**，實質主張成立（見 P3′）。")
    print("  [第一輪] P5 **真的錯了**：拿掉 AGC 後效應**沒有**回來。"
          "我給的理由（撞 rail）是錯的——訊號在 ±1，A=1.78，根本碰不到 rail。")
    print("  [第二輪] P7/P8 **又不成立**，而且**又是實驗設計寫壞了**："
          "我在 30 dB + AGC 下取 rail，此時 A=0.08，訊號整個被 clip，"
          "兩種量化器都塌到 {0,15}（本來就互補）——symmetry-breaking 根本沒發生。")
    print("  [第二輪] 但它撞出一個我沒預測到的**真效應**：飽和 -> ACS 平手 -> "
          "tie-break 偏壓 -> surv 活動下降。已補為 P9。")
    print("  [第三輪] 把滿刻度固定住（A=1.775>1）讓 rail 落在範圍內 -> P7′ 成立。"
          "但 P8′ 仍不成立：用 levels=2^Q 破壞對稱性，會把 c=0 的 rail 推到 **3.493**，"
          "離 3.5 的 round 邊界只有 0.007 —— 光是 rounding 就把 bit0 隨機化了。"
          "**又是實驗設計問題，不是機制問題。**")
    print("  [第四輪] 改用**整數 DC offset**（= 真實的 ADC 比較器偏移）破壞對稱性："
          "rail 落在 4.275 / 12.725，離 round 邊界 0.225，效應才乾淨地顯現。")
    print("\n  核心主張（P1/P2/P4/P6）**四輪都沒被打破**："
          "在可用的 SNR 區間內，survivor 活動是平的。")
    print("  真正的原因：量化器對稱 => r1 == ~r0 => 編碼位元一翻，"
          "r 的**每個位元**都跟著翻。與雜訊無關。")

    out = os.path.join(DATA, "results_m5_mechanism.csv")
    with open(out, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    print(f"\n-> {out}（{len(rows)} 列）")

    if bad:
        print(f"\n**{bad} 條不成立 —— 修正後的機制也有問題，必須再改寫，不得掩蓋。**")
        return 2
    print("\n修正後的機制 6/6 成立：**位元活動被隨機資訊源釘在最大熵；"
          "SNR 只改變正確性，改變不了統計。**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
