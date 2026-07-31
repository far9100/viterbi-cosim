"""design.py — 設計組態與 RTL 檔案清單的單一來源。

## 為什麼需要它

同一份資訊先前散在很多地方：

* **M2 選出的 4 組 winner** 出現在 `ppa/synth.py`、`ppa/sta.py`、`ppa/run_power.py`、
  `scripts/tier_b.py`、`scripts/m9_sweep.py` —— 五份各自維護的字面值。
* **RTL 檔案清單**（7 個模組）出現在 `tb/cocotb/_run_group.py`、`scripts/tier_b.py`、
  `ppa/synth.py`、`scripts/check_rtl.sh`、`scripts/g7_icarus.sh` —— 五份。
  加一個模組要改五個地方，而其中只有兩個會大聲失敗。

## 順序是有意義的，不能抹平

**單一來源不等於單一順序。** 各消費端輸出的 CSV，其列序就是它迭代 winner 的順序：

    ppa/sta.py     -> data/results_m5_fmax.csv   列序 Q4, Q6_D64, Q6_D32, Q3
    ppa/synth.py   -> 合成順序（不進 CSV，但影響 log）

`ppa/synth.py` 與 `scripts/tier_b.py` 用的是一種順序，`ppa/sta.py`、`ppa/run_power.py`
與 `scripts/m9_sweep.py` 用的是另一種。把它們統一成一個順序會改變已提交 CSV 的列序，
**破壞冷跑的逐位元組判準** —— 而那個判準是本專案最強的一條檢查，不能為了程式碼整潔而動它。

所以這裡的單一來源是**組態的定義**（Q, W, D, clip），順序則由各消費端明文宣告。
兩種順序都列在下面，並註明各自的來歷；要改順序就必須同時面對「已提交的 CSV 會變」。
"""

# tag -> (Q, W, D, clip)。clip 由 M2 的網格掃描選出（data/m2_winners.csv）。
WINNERS = {
    "Q6_W12_D64": (6, 12, 64, 3.0),   # BER 最佳（不計成本）
    "Q6_W12_D32": (6, 12, 32, 3.0),   # D 最小，survivor 記憶體支配面積
    "Q4_W10_D64": (4, 10, 64, 2.5),   # Q 最小，Q 唯一決定最小安全 W
    "Q3_W8_D32":  (3,  8, 32, 2.0),   # 教科書組態（對照）
}

# 合成與 Tier B 的迭代順序（沿用 M3/M4/M5 建立時的順序）
ORDER_SYNTH = ["Q6_W12_D64", "Q6_W12_D32", "Q4_W10_D64", "Q3_W8_D32"]

# STA / 功耗 / M9 的迭代順序：主掃描組態（Q4_W10_D64）排第一，
# 因為「功耗 vs SNR」的交付結果就是在它上面量的。
# data/results_m5_fmax.csv 的列序即由此決定。
ORDER_POWER = ["Q4_W10_D64", "Q6_W12_D64", "Q6_W12_D32", "Q3_W8_D32"]

# M9 的兩個 RTL 變體（B0′ / B1′），tag 後綴 -> 是否插 clock gating
VARIANTS = [("_rtlv", False), ("_cg_rtlv", True)]

# 7 個 RTL 模組。目錄由呼叫端給（rtl/ 或 rtl_lowpower/）。
MODULES = [
    "bmu.sv", "acs_butterfly.sv", "acs_array.sv", "minpm.sv",
    "traceback.sv", "ctrl.sv", "viterbi_top.sv",
]


def winners(order):
    """依指定順序回傳 [(Q, W, D, clip), ...]。order 必須是本檔宣告的兩個之一。"""
    assert order in (ORDER_SYNTH, ORDER_POWER), \
        "順序必須用本檔宣告的其中一個 —— 自訂順序會改變輸出 CSV 的列序"
    return [WINNERS[tag] for tag in order]


def rtl_files(rtl_dir="rtl"):
    """回傳該目錄下的 7 個 RTL 檔（相對 repo 根目錄）。"""
    return [f"{rtl_dir}/{m}" for m in MODULES]


def tag_of(Q, W, D):
    return f"Q{Q}_W{W}_D{D}"
