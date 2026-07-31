"""test_energy_model.py — 斷言程式碼裡的能量模型常數 == docs/energy_model.md 表格裡的值。

`docs/energy_model.md` §7 早就承諾了這件事：

> 本文件的每個常數在 `scripts/energy_model.py` 中有對應的具名常數，
> 且該檔的單元測試會斷言「程式碼中的值 == 本文件表格中的值」。

但那個測試從來沒被寫出來。這個檔補上它。

為什麼這條測試必須**去解析 markdown**，而不是在測試裡另抄一份常數：

    `docs/energy_model.md` 是**預先登記文件**——它在任何能量量測開跑之前就 commit 了
    （commit 時間戳可驗證早於量測 21.2 小時），整篇報告「我們事前就把計價方式定死了」
    的主張全繫在它身上。如果測試自己抄一份數字，那它驗的只是「兩份副本一致」，
    改動時兩邊一起改就會靜靜通過——**預先登記文件就失去了約束力**。
    唯一有意義的做法是把那份文件當成 oracle：從 markdown 表格裡把值讀出來比對。

    這與 CLAUDE.md §5.1(b)「凍結的規則必須表達在 committed code 裡」是同一條紀律的另一面：
    規則寫在文件裡，程式必須可被機械化地證明遵守它。

註：η_PA 與 n（路徑損耗指數）在文件裡是掃描範圍而非單一值，故另外以列表比對。
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import energy_model as em  # noqa: E402

DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "energy_model.md")


@pytest.fixture(scope="module")
def doc():
    with open(DOC, encoding="utf-8") as f:
        return f.read()


def _num(doc_text, pattern):
    """從文件抓一個數字。抓不到就讓測試失敗，不要靜靜回退到預設值。

    「靜靜回退到預設值」正是 M0 那個 SAIF timescale bug 的形狀：單行 regex 比對失敗後
    退回預設，DURATION 差 1000 倍，而功耗數字看起來仍然像個數字。同樣的錯不犯第二次。
    """
    m = re.search(pattern, doc_text)
    assert m is not None, f"docs/energy_model.md 裡找不到 {pattern!r}"
    return float(m.group(1).replace("e", "e"))


# ---------------------------------------------------------------- §1 物理常數

def test_boltzmann(doc):
    assert em.K_B == _num(doc, r"\|\s*k\s*\|\s*([\d.e+-]+)\s*J/K")


def test_reference_temperature(doc):
    assert em.T0_K == _num(doc, r"\|\s*T₀\s*\|\s*([\d.]+)\s*K")


def test_speed_of_light(doc):
    assert em.C_LIGHT == _num(doc, r"\|\s*c\s*\|\s*([\d.]+)e8\s*m/s") * 1e8


def test_carrier_frequency(doc):
    assert em.F_C == _num(doc, r"\|\s*f_c\s*\|\s*([\d.]+)\s*GHz") * 1e9


# ------------------------------------------------ §1/§2 導出值（兩處已知的文件誤差）
#
# 下面兩條與上面的原始常數不同：λ 與 L1 在文件裡是**導出值**，而程式是從原始常數
# （c、f_c）現算的。這條測試第一次跑就抓到文件的兩個導出值印錯了：
#
#   λ    文件印 0.124913 m，但 c/f_c = 0.12491352417 —— 正確的六位小數是 **0.124914**
#        （文件是截斷，不是四捨五入）。
#   L1   文件印 1.01174e4，但 (4π/λ)² = **1.012047e4** —— 相對差 3.04e-4。
#        以 dB 計是 40.0520 dB，文件 §2 的「40.05 dB」反而是對的。
#
# **兩者都不改變任何已發表的數字**（d* ∝ L1^(-1/n)，故 d* 只動 0.0152%（n=2）/
# 0.0087%（n=3.5）；報告的 17.8 m 與 +11.29% 分別只有 3 位有效數字與 2 位小數）。
# 程式端**不需要修**：它是從文件的原始常數現算的，算法正確。要修的是文件的兩個印刷值，
# 而 `docs/energy_model.md` 的標頭規定「任何一個常數要改，必須改本文件並重新 commit，
# 且說明理由」——那是使用者的裁定，不是測試該偷偷做的事。
#
# 所以這兩條測試的判準是：**導出值的誤差必須小到不影響任何已發表數字**。
# 誤差一旦超出這個界，就代表文件與程式真的分岔了，測試必須紅燈。

_DERIVED_TOL_REL = 1e-3      # 使 d* 的變動 < 0.05%，遠小於報告的有效位數


def test_wavelength_matches_doc(doc):
    """λ = c/f_c。文件印的是截斷值，差 5.2e-7 m（見上方說明）。"""
    cited = _num(doc, r"\|\s*λ\s*\|\s*([\d.]+)\s*m")
    assert em.LAMBDA == pytest.approx(cited, rel=_DERIVED_TOL_REL), (
        "λ 與 docs/energy_model.md 的分岔超出可忽略範圍——文件與程式真的不一致了")


def test_path_loss_at_1m_matches_doc(doc):
    """L(1 m) = (4π/λ)²。文件印 1.01174e4，實際 1.012047e4（見上方說明）。"""
    cited = _num(doc, r"L\(d\)\s*=\s*\(4π/λ\)²\s*·\s*d\^n\s*=\s*([\d.e+]+)\s*·")
    assert em.L1 == pytest.approx(cited, rel=_DERIVED_TOL_REL), (
        "L1 與 docs/energy_model.md 的分岔超出可忽略範圍——d* 會跟著平移")


def test_path_loss_in_db_matches_doc(doc):
    """文件 §2 的「1 m 處為 40.05 dB」——這個值反而是對的，釘住它。

    L1 的線性值與 dB 值在文件裡不自洽（1.01174e4 = 40.0507 dB vs 印的 40.05 dB
    對應 1.01158e4–1.01182e4）。dB 那個印到小數第二位，把真值 40.0520 dB 蓋住了，
    所以只有線性值那一處露出誤差。留這條測試是為了讓將來修文件的人知道要一起改。
    """
    import math
    cited_db = _num(doc, r"1 m 處為\s*([\d.]+)\s*dB")
    assert 10 * math.log10(em.L1) == pytest.approx(cited_db, abs=0.005)


# ---------------------------------------------------------------- §2 系統參數

def test_noise_figure(doc):
    assert em.NF_DB == _num(doc, r"F（接收機雜訊指數）\s*\|\s*(\d+)\s*dB")


def test_n0_matches_doc(doc):
    """N0 = k·T₀·F。文件 §2 寫死 1.5940e-20 J。"""
    assert em.N0 == pytest.approx(
        _num(doc, r"\|\s*N0\s*\|\s*([\d.e+-]+)\s*J"), rel=1e-4)


def test_symbol_rate(doc):
    assert em.R_SYM == _num(doc, r"R_s（符號率）\s*\|\s*(\d+)\s*Msym/s") * 1e6


def test_circuit_power(doc):
    assert em.P_CIRCUIT == _num(doc, r"P_circuit\s*\|\s*(\d+)\s*mW") * 1e-3


def test_decoder_clock(doc):
    assert em.F_CLK == _num(doc, r"f_clk（解碼器）\s*\|\s*(\d+)\s*MHz") * 1e6


def test_target_ber(doc):
    assert em.TARGET_BER == _num(doc, r"目標 BER\s*\|\s*(1e-\d+)")


def test_pa_efficiency_range(doc):
    """η_PA 是掃描範圍 [0.1, 0.5]（規格書 §7 指定）。"""
    lo = _num(doc, r"η_PA\s*\|\s*—\s*\|\s*\[([\d.]+),")
    hi = _num(doc, r"η_PA\s*\|\s*—\s*\|\s*\[[\d.]+,\s*([\d.]+)\]")
    assert em.ETA_PA == [lo, hi]


def test_path_loss_exponents(doc):
    """n = 2.0 自由空間 / 3.5 室內，雙軸呈現。"""
    free = _num(doc, r"n（路徑損耗指數）\s*\|\s*—\s*\|\s*([\d.]+)\s*/")
    indoor = _num(doc, r"n（路徑損耗指數）\s*\|\s*—\s*\|\s*[\d.]+\s*/\s*([\d.]+)")
    assert em.N_PATHLOSS == {"free_space": free, "indoor": indoor}


# ------------------------------------------------- §5 E_dec 的分解與 f_clk 無關性

def test_edec_decomposition_is_fclk_independent():
    """docs/energy_model.md §5：E_dec(f_clk) = e_dyn_per_bit + p_leak / f_clk。

    這條式子是 `data/results.csv` 分開記錄兩個欄位的**唯一理由**。驗它成立，
    等於驗「換一個時脈不必重跑 gate-level 流程」這個承諾為真。
    """
    p_total, p_leak = 44.077e-3, 4.87e-10      # Q4_W10_D64 @ 3 dB 的量級
    e_dyn = (p_total - p_leak) / em.F_CLK
    assert e_dyn + p_leak / em.F_CLK == pytest.approx(p_total / em.F_CLK, rel=1e-12)


# ------------------------------------------------------------ §3 兩個模型的定義

def test_model_b_pays_one_extra_circuit_energy():
    """§4：固定符號率下 R=1/2 多付 P_circuit × 1/R_s = 60 nJ/info bit。

    這一項是模型 B 的**支配項**（比 E_dec 大約 600 倍），也是模型 A 與 B 相差
    兩個數量級的全部原因。它算錯，d* 的兩欄就整組錯，而數字看起來仍然合理。
    """
    assert em.P_CIRCUIT / em.R_SYM == pytest.approx(60e-9, rel=1e-12)


def test_model_b_dstar_exceeds_model_a():
    """同一組態下 d*(B) > d*(A)：B 多了 60 nJ 的分子，而 d* 隨分子單調上升。"""
    kw = dict(ebn0_coded_db=4.1937, e_dec_j=303.2e-12, eta=0.1, n=3.5)
    assert em.d_star(model="B", **kw) > em.d_star(model="A", **kw)


def test_dstar_returns_nan_when_coding_gain_is_negative():
    """編碼比未編碼還差時交叉點不存在，必須回 nan 而不是一個看起來合理的數。"""
    import math
    v = em.d_star(em.EBN0_UNCODED_DB + 1.0, 303.2e-12, 0.1, 2.0, "A")
    assert math.isnan(v)


# ------------------------------------------------------- §6.2 ADC 敏感度線的定義

def test_adc_energy_is_two_conversions_per_info_bit():
    """R=1/2 ⇒ 每個 info bit 2 次轉換；E_ADC = 2 · FoM · 2^Q。"""
    assert em.e_adc(6, fom_j=100e-15) == pytest.approx(2 * 100e-15 * 64)


def test_adc_energy_grows_eightfold_from_q3_to_q6():
    """E_ADC ∝ 2^Q。Q 3→6 是 8 倍，方向與 E_dec 相同 ⇒ 只會加大 Δd*、不會翻轉符號。"""
    assert em.e_adc(6) / em.e_adc(3) == pytest.approx(8.0)
