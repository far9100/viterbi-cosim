# fec-cosim —— K=7 soft Viterbi 的 bit-accurate co-simulation

把既有的純軟體通訊鏈路模擬器（numpy 浮點 Monte Carlo BER），延伸成一條
**numpy → 定點 golden model → RTL → gate-level PPA** 的逐層 bit-accurate 驗證鏈路，
並用它回答一個可證偽的工程問題：

> 總能量 = 發射能量 + 解碼能量。強碼（K=7 soft Viterbi）省下約 5 dB 發射功率，
> 但要付解碼器的功耗。所以存在一個臨界距離 d\*，**低於 d\* 時未編碼傳輸的每交付位元總能量反而較低**。
> 本專案量測 d\* 的位置，以及 LLR 量化位寬（3–6 bits）如何移動它。

**誠實定位**：這個 crossover 在低功耗 WSN/BAN 文獻中是已知效應。本專案的貢獻不是發現它，
而是用一條自建、可復現、**逐層 bit-accurate 驗證**的鏈路把它重新量出來。

完整規格見 `docs/fec_viterbi_cosim_spec.md`。

## 三層模型與兩個比對點

```
L1  浮點參考模型（float64）
 │   C1: 量化損失 —— 以 dB 計價，不是 pass/fail
L2  定點 golden model（整數 numpy；GPU 掃描用 torch 整數版）
 │   C2: 位元級相等 —— 零容忍，每 stage 比對 bm / pm / survivor / 解碼位元
L3  RTL（SystemVerilog，Verilator + Icarus）
```

再加上兩個 v1 規格書漏掉的比對點：

- **C2′**：L2-CPU vs L2-GPU 位元級相等。`torch.minimum` 不回傳索引，GPU 版的 survivor bit 要自己算，
  而 `<=` 與 `<` 的選擇會**默默決定平手方向**——Q=3 時整數平手很常見，選錯不會報錯。
- **G7**：Verilator（2-state）vs Icarus（4-state）交叉檢查。Verilator 把未初始化的暫存器讀成 0 而非 X，
  會靜默隱藏 reset 不完整的 bug。

## 環境

全部跑在 **WSL2 Ubuntu 24.04**（Windows 上沒有 C++ toolchain，且 Python 3.14 與 cocotb 不相容）。

| 工具 | 版本 | 來源 |
|---|---|---|
| Verilator | 5.051 | oss-cad-suite（免 root） |
| Icarus Verilog | 14.0 | oss-cad-suite |
| Python | 3.12 + `.venv` | numpy 2.4.4（與既有模擬器對齊，確保重跑可逐位元組比對） |
| torch | 2.11.0+cu128 | sm_120（RTX 5070）已驗證整數路徑 |
| Yosys / OpenROAD / OpenSTA / Sky130 | 0.64 / 26Q3 / 3.1.0 | `openroad/orfs:latest` Docker image |
| sky130 cell models | commit `ac7fb61f` | vendored，見 `ppa/models/PROVENANCE.md` |

```bash
bash scripts/setup_venv.sh    # Python venv
bash scripts/setup_eda.sh     # Verilator + Icarus（免 root）
bash scripts/setup_gpu.sh     # torch cu128 + sm_120 整數 kernel 驗證
bash scripts/setup_models.sh  # sky130 behavioral cell models
make env                      # M0 驗收閘門
```

## 一鍵重跑

```bash
make env      # M0：工具鏈驗收（Verilator/Icarus、GPU、gate-level 功耗流程）
make m1       # M1：L2 golden model + G1-G4
make m2       # M2：GPU 設計空間掃描 + C2′
make m3       # M3：RTL + Tier A（C2 / G6 正反向 / G7）
make m4       # M4：Tier B 浸泡（2.47 億個 stage）
make m5       # M5：合成 -> gate-level -> SAIF -> OpenSTA -> d*
make figures  # 重生所有圖表
make report   # check_paper_numbers.py，必須輸出 mismatches: 0
make mutate   # 變異測試：檢查器必須抓得到錯（6/6）

make all      # 以上全部
make repro    # **冷跑**：刪光 data/ 從零重生，逐位元組驗證
```

報告裡的每個數字都必須存在於 `data/gates.csv` 或 `data/results_m*.csv`，
且可由 `scripts/` 底下的 script 重生。手貼的數字不接受（CLAUDE.md §5.4）。
`make report` 把這條紀律機械化：**226 條 assertion，每一條都同時驗
「值等於 CSV 算出的真值」與「該字串確實出現在報告中」**（防止斷言與文件脫節）。

**`make repro` 會真的把 `data/` 刪光重生**，然後用 `git status` 檢查：除了
`data/meta_*.json`（時間戳與 wall time，本來就會變）以外，每一個檔案都必須**逐位元組相同**。
（在 2026-07-15 之前，這份 Makefile 的 `sweep` / `ber` / `report` 其實印的是
「尚未開始」——「一鍵重跑」是一句從未被測試過的宣稱。見 `CHANGELOG.md`。）

## 目前進度

| 里程碑 | 狀態 |
|---|---|
| M0 環境建置與工具鏈驗證 | **完成**（E1/E2/E3 全綠，tag `m0-env`） |
| M1 L2 定點 golden model + K=7 浮點參考 | **完成**（G1/G2a/G2b/G3/G4a/G4b 全綠，tag `m1-golden`） |
| M2 GPU 掃描 | **完成**（C2′ 零 mismatch，全網格，4 組 winner，tag `m2-sweep`） |
| M3 RTL + Tier A | **完成**（C2 22,532 stages 零 mismatch，G6 負向 4/4，G7 通過，tag `m3-rtl`） |
| M4 Tier B + G6 浸泡 | **完成**（2.47 億 stage 浸泡零 mismatch，tag `m4-tierb`） |
| M5 PPA + 能量模型 | **完成**（8 個點 100% annotation，三條證偽條件全部裁決，tag `m5-ppa`） |
| M6 報告 + 數字稽核 | **完成**（226 條 assertion / 0 mismatch，變異測試 6/6，tag `m6-report`） |
| M7 完整冷跑（可重生性） | **完成**（`make repro` 刪光 `data/` 從零重生、逐位元組相同，tag `m7-repro`） |

**專案定案（2026-07-17）：規格書 §10 的六項 Definition of Done 全部達成並實測驗證。**
已揭露的邊界（d\* 為上界、PPA 僅 full-parallel、ADC 敏感度線、折疊/post-route/memory-traceback 未做）
見 `docs/report.md` §5，不因定案而默示為已驗證。

完整報告見 **`docs/report.md`**。

### M1 的主要結果

所有數字出自 `data/results_m1.csv`，可由 `make gates` 重生。

| 量 | 實測 | 參考 |
|---|---|---|
| 未編碼 BPSK @1e-5 | **9.571 dB** | 閉式解 9.588；既有模擬器獨立量到 9.5842 |
| K=7 軟判決（未量化, D=64）@1e-5 | **4.137 dB** | union bound 給 4.200 |
| **編碼增益 @1e-5** | **5.434 dB** | 事前登記 5.39（`docs/falsification.md`） |
| 硬判決 @1e-5 | **6.550 dB** | union bound 給 6.555 |
| 硬判決損失 | **2.413 dB** | union bound 給 2.355 |
| 3-bit 量化損失（最佳 clip 2.5σ） | **0.225 dB** | Heller & Jacobs 的 0.2 dB |
| D=24 相對全幀 ML 的損失 | **+0.209 dB** | D=32/48/64 落在雜訊內 |
| C1 的量測雜訊地板 | **±0.076 dB** | Q≥4 的損失小於此，需 M2 才分辨得出 |

**規格書 v1 的 G2 與 G4 兩道閘門的容差都被證明是錯的**（union bound 這條定理本身就落在
它們的區間之外）。G2 在開跑前就抓到並修正；G4 是量測之後才發現，已如實標示為事後修正。
細節見 `docs/fec_viterbi_cosim_spec.md` §6 與 `CHANGELOG.md`。

### M2 的主要結果

**設計空間從 (Q, clip, W, D) 塌成 (Q, clip, D)。** W 不是 BER 的軸——這是 G6 的推論
（modulo 決策等價 ⇒ 決策與 W 無關 ⇒ 解碼位元與 W 無關），且由 C2′ **直接比對解碼位元**
驗證，不是假設。每個 Q 的最小安全 W 由字寬界唯一決定（3→8, 4→10, 5→10, 6→12），
PPA 上沒有選擇餘地。W 只影響面積與功耗。

**Winner 組態**（理由已記錄；刻意不造綜合成本分數——真正的硬體成本要等 M5 合成）：

| 組態 | 所需 Eb/N0 | 損失 | survivor 記憶體 | 挑選理由 |
|---|---|---|---|---|
| Q=6, clip=3.0σ, W=12, D=64 | 4.152 dB | +0.015 | 12288 bits | BER 最佳（不計成本） |
| Q=6, clip=3.0σ, W=12, D=32 | 4.194 dB | +0.057 | **6144 bits** | 記憶體減半，只付 +0.04 dB |
| Q=4, clip=2.5σ, W=10, D=64 | 4.191 dB | +0.054 | 12288 bits | Q 最小 → ADC 與 ACS 最省 |
| Q=3, clip=2.0σ, W=8, D=32 | 4.359 dB | +0.222 | 6144 bits | 教科書組態（對照） |

**G6 的負向展示**（`figures/fig_m2_ber_floor.png`）：字寬不足時 **BER 不降反升**。
安全組態在 4.0→5.5 dB 掉 2.58 個數量級；不安全的 (Q=4,W=8) 在 4→7 dB 反而從 4e-4
**升到 5e-2**，而 (Q=5,W=8)、(Q=6,W=8) 直接釘在 **BER = 0.5（等同擲硬幣）**。

### M3 + M4 的主要結果：C2 的對外宣稱

> **Tier A：32 組 (Q,W,D) × 86 個 frame × 22,532 個 stage 比對，0 mismatch。**
> 每個 stage 比對 `bm[4]`、`pm[64]`、`survivor[64]`、**解碼位元**。
>
> **Tier B：12 個點 × 245,760,000 個資訊位元 / 247,200,000 個 trellis stage，0 mismatch。**
> 相對 Tier A 擴大 10,971 倍。SHA-256 12/12 對帳相符。

**我們不量 RTL 的 BER。** C2 已證明 RTL ≡ golden 逐位元相等，所以兩條 BER 曲線在數學上
**是同一條**；重跑上億位元去「重新量」一條已知的曲線不是驗證，是算術。
BER 由 golden 以 100× 的樣本數量得（M1/M2）。這是方法學上的強項，不是抄捷徑。

**C2 抓到的第一個 RTL bug，正是它存在的理由**：`traceback` 被餵了打拍後的 survivor。
`bm` / `pm` / `survivor` / `best` **全部完全正確**，只有解碼位元在 frame 頭尾錯掉
（256 個位元裡錯 3 個）。**全零向量完全測不出來。** 只比 bm/pm/survivor 的 C2
會讓它完整通過——這就是「解碼位元必須納入比對集」的理由。

**G6 assertion**：M3 證明它在 4 個不安全格點上於 **stage 0** 觸發（實測 spread 181/382/808/776
分別超過 2^(W−1) 的 128/128/128/512）；M4 證明它在 **2.47 億個 stage** 的低 SNR 浸泡中**全程靜默**。

### M5 的主要結果：d\*、以及三條預先登記的證偽條件

功耗由**真實 AWGN 通道資料驅動**的 gate-level switching activity 算出，
**8 個點的 SAIF annotation coverage 全部 100%**。

**三條證偽條件全部不觸發，主張存活**（`docs/falsification.md` 於量測前 21.2 小時 commit，
git 時間戳可驗證）：

| 條件 | 實測（附 95% 區間） | 裁決 |
|---|---|---|
| **F1** d\* < 1 m 或不存在？ | 所有模型/環境/η 下的最小 d\* = **17.8 m**（[17.60, 17.91]） | 不觸發 → 存活 |
| **F2** 兩模型下 \|Δd\*\| 皆 < 5%？ | 模型 A **+11.29%** [+10.84, +11.75]（自由空間）/ **+6.31%** [+6.06, +6.55]（室內） | 不觸發 → 存活 |
| **F3** 符號：A 正、B 負？ | A **正**、B **負**（−0.75% [−1.05, −0.45] / −0.43% [−0.60, −0.26]） | 不觸發 |

**「符號會翻轉」這條事前預測確認成立**——同一組 RTL、同一組功耗量測，
在兩個能量模型下 d\* 對 Q 的斜率**符號相反**。模型 B 的量級幾乎完全命中
（事前 −0.87% / −0.50%，實測 −0.75% / −0.43%）。

**而且它是被解析出來的，不是雜訊。** 不確定度以參數化 bootstrap 從 BER 的 cluster-robust CI
一路傳到 required Eb/N0、d\*、Δd\*（`golden/ber.py` 的 `required_ebn0_ci`、
`scripts/energy_model.py` 的 `d_star_ci` / `delta_dstar_ci`）。
**四個 Δd\* 的 95% 區間全部不跨過零點，模型 A 的兩個完全落在 5% 門檻之外。**
`check_paper_numbers.py` 把這件事釘成硬性檢查：任一區間跨零，`make report` 就紅燈，
報告不得再宣稱「符號會翻轉」。

同一套區間也顯示**反面**的事：三個 winner（Q6/D64、Q4/D64、Q6/D32）的 required Eb/N0
為 4.152 / 4.191 / 4.194 dB，而各自的 σ 是 0.0239 / 0.0225 / 0.0208 dB
—— **它們之間的排序在統計上是平手**，「BER 最佳」只在點估計的意義上成立。

**但我的 α 點估計錯了 3.4 倍**（事前登記 0.15，實測 **0.517**），已如實記錄。
兩個錯誤都可量測：traceback 佔 **67.7–84.1% 的 flop** 卻只佔 **43.0–54.2% 的功耗**；
而我**完全漏掉了 min-PM 的 argmin 樹**——它佔 **10.3–13.5% 的功耗**、**11.8–19.7% 的面積**，
**比整個 PM register file 還大 2.21–2.45 倍**。這是選 best-state traceback（而非 fixed-state）
的直接代價。

**Fmax：純邏輯合成的 netlist 上報 Fmax 是沒有意義的。** 直接跑 OpenSTA 得到 **166.81 ns
（6.0 MHz）**，但關鍵路徑是**一顆最小尺寸的反相器扛 8683 個 sink / 18.10 pF**——
`u_ctrl` 的 enable 直接扇出到 register exchange 的全部 flop，中間沒有任何 buffer tree
（Yosys 的 `abc` 只做技術映射，不做負載感知的 buffer 插入）。
跑 OpenROAD 的 `repair_design` 之後 **150.2 MHz**，四個組態全部 **≥ 101.2 MHz > 100 MHz**
⇒ 能量模型假設的 f_clk 站得住。

### 規格書要的那條曲線不存在（而機制比它有價值）

規格書 §7 把「功耗對 SNR 的依賴曲線（低 SNR → ACS toggle 率高 → 功耗高）」列為交付結果。
**實測：總功耗在 1→5 dB 只變動 1.0%，非單調，方向還與前提相反。分區塊也救不了它。**

追下去的機制（`scripts/diag_mechanism.py` 的 numpy golden 與 `ppa/saif_toggle.py` 的
gate-level SAIF **兩條獨立路徑交叉驗證**，吻合到 1% 以內）：

> 量化器是對稱的：`r(c=1) = (2^Q − 1) − r(c=0)`，而 `2^Q − 1` 是全 1，
> 所以那**就是 `~r(c=0)`**（位元補數）。BPSK 的兩個假設被映到**位元互補**的碼。
> 編碼位元是 i.i.d. uniform ⇒ 編碼位元一翻，**r 的每個位元都跟著翻**。
>
> 而狀態遞迴使「正確的 survivor bit」**就是 `u[t−6]`——資訊位元本身**（以代數斷言驗證）。
>
> ⇒ **一個完美的 Viterbi 解碼器，與一個完全失效的，其 survivor 記憶體的切換活動一模一樣。**

**倖存者翻轉率對 SNR 的線性迴歸 R² = 0.000**（路徑度量 `pm` 是唯一有系統性趨勢的訊號，
R² = 0.913——因為它是整條路徑上唯一不在最大熵的訊號，它是**累加器**）。

**反事實證明機制**：加一個整數 DC offset（＝真實 ADC 的比較器偏移）打破位元互補性，
兩個 rail 在某些位元上變成相同 ⇒ **那些位元的翻轉率從 0.5042 崩到 0.0000**。
定律 `toggle(k) = 0.5 · 1{bit k 在兩個 rail 上相異}` 精確成立。

**推論超出本專案**：任何接收「編碼過（＝白化過）」訊號的解碼器，其資料路徑活動都會與 SNR 無關
——編碼的作用本來就是白化。SNR 只改變位元的**正確性**，而 switching power 只看**統計**。

### M6：把「數字與資料一致」從人工目視升為機械保證

`make report` 跑 `scripts/check_paper_numbers.py`：**226 條 assertion，mismatches: 0**。
每一條同時驗兩件事——(a) 值等於 CSV 算出的真值；(b) 該字串**確實出現在文件中**
（防止斷言與文件脫節）。外加：

- **預先登記的 commit 時間戳必須早於量測**（實測早 **21.2 小時**，git 可驗證）。
  不機械化驗證這一條，「我們事前就登記了」就只是一句自稱。
<!-- R3-exempt -->
- **已撤回主張的字面回歸防護**：把「被自己的資料推翻過的說法」釘死，防止它悄悄復活。
  （這一段本身要**引用**那些被禁的字樣才能說明它在擋什麼，所以用 `R3-exempt` 標記豁免。
  全專案只允許一個豁免區——豁免會讓 R3 對其中的內容失明，不得增設。）
  被擋的例子：「pm 隨 SNR 單調上升」、「SNR 依賴住在 ACS」。
<!-- /R3-exempt -->
- **帶單位的數字覆蓋掃描**：報告與 README 裡任何沒對回 CSV 的數字都會讓 `make report` 失敗。

涵蓋 `docs/report.md` 與本 README，外加 **36 筆 gate 記錄**（30 個有判準的 gate + 6 筆觀測）的完整性檢查。
（連「226 條」這句話本身都被驗——README 說幾條就必須真的有幾條。這條會在每次新增 assertion 時
壞掉，那正是它的用途：逼 README 跟著更新，而不是慢慢變成一句過期的自我吹噓。）

`make mutate` 是**檢查器自己的變異測試**——一個抓不到錯的檢查器沒有價值。
注入 6 種已知錯誤，**6/6 全部抓到**。它抓到過檢查器的三個真洞，其中最嚴重的是
**coverage gap 不影響 exit code**（於是改壞一個數字，CI 會綠燈放行）。

### 誠實的界線：**沒有**驗證的東西

1. **d\* 的絕對值是上界**：survivor 記憶體用 flop 陣列而非 SRAM macro ⇒ 高估 E_dec ⇒ 高估 d\*。
   Q 之間的**相對**比較不受影響（同一個 D 下 traceback 功耗實測只差 0.08%）。
2. **Fmax 是 post-placement / pre-route**，無真實繞線寄生、無 clock tree ⇒ **樂觀**。
3. **ADC 能量是敏感度線，不是量測值**（Walden FoM）。
4. **PPA 表只涵蓋 full-parallel（PAR=32）。** 折疊架構（PAR=8/1）、post-route P&R、
   memory traceback 對照、SRAM macro 版本**都沒做**，不得默示為已驗證。
5. **機制那條結論我試錯了四輪**（其中兩輪是**實驗設計**寫壞，不是機制錯），
   全部保留在 `scripts/diag_mechanism.py` 的 docstring。核心主張四輪都沒被打破。
