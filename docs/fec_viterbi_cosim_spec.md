# FEC 解碼器 RTL 與 bit-accurate co-simulation — 專案規格書

> 本文件是給 coding agent 的完整工作規格。所有設計決策已定案，agent 的任務是依規格實作、驗證、產出數據，**不要**自行更改架構層級、比對點定義或驗證閘門。任何規格模糊處，先停下來詢問，不要自行假設。

---

## 修訂記錄

**2026-07-14（v2，M0 完成時）**：本文件 v1 的若干前提經實測後不成立，且有數處內部矛盾。
以下修訂已套用，全部發生在**任何量測開跑之前**：

| # | v1 的問題 | 修訂 |
|---|---|---|
| A1 | 「L1 = 既有 numpy 鏈路」 | 既有模擬器只有 **K=3 (7,5)、4-state 硬編碼 trellis** 的 Viterbi。**K=7 浮點參考不存在**，M1 必須新寫。見 §2.2。 |
| A2 | 「複用 RISC-V 專案的 VCD/SAIF → OpenSTA 功耗流程」 | 該流程**從未被建置**（RISC-V 的功耗是 vectorless 假設值，其論文列為未竟事項 FW4）。M0 已從零建置並驗收通過。見 §7。 |
| A3 | 「OpenLane 2」 | 該專案從未用過 OpenLane。實際資產是 **ORFS Docker image**（Yosys 0.64 / OpenROAD 26Q3 / OpenSTA 3.1.0 / Sky130）。 |
| A4 | 預設 Verilator/cocotb 已就位 | 兩者原本都不存在。M0 以 oss-cad-suite 安裝（Verilator 5.051 / Icarus 14.0）。 |
| B1 | §3 說 branch metric 是相關度量（取最大），§5 卻說用 `torch.minimum`（取最小） | 改為等價的**非負整數距離度量**，取最小。見 §3。 |
| B2 | §6 G6 的不變式未涵蓋初始化 | 正確條件為 `2^(W−1) > 14·(2^Q−1)+1`。見 `docs/wordlength_bound.md`。 |
| B3 | §6 G2「增益 ≈ 5 dB ±0.3」 | union bound 給出未量化下的增益 ≈ 5.3–5.5 dB，落在容差外。改為兩段式 G2a/G2b。見 §6。 |
| B4 | §7 流程圖的 SAIF | **保留**（初審誤判為可省略）。gate-level VCD 是 30–180 KB/cycle，必須串流轉 SAIF。見 §7。 |
| B5 | §8 的 `rtl/sva/pm_invariant.sv` | Icarus 不支援 `bind`，兩個模擬器都不給可用的 concurrent SVA。改為 `always_ff` 內的 immediate assertion。 |
| B6 | §5「384 runs」 | 漏掉 clip 軸。GPU 全網格是 ≈1920 點。另 §3 的 traceback 延遲「= D」應為 **2D–3D**。 |
| C1 | §0 的證偽條件 | 「d\* < 1 m」實質不可能觸發（估計 d\* ∈ [13.7 m, 5.4 km]）。條件原樣保留，另追加兩條真正可證偽的預先登記。見 `docs/falsification.md`。 |
| — | 缺環境建置里程碑 | 新增 **M0**。見 §9。 |

修訂的完整推導見 `docs/falsification.md`、`docs/energy_model.md`、`docs/wordlength_bound.md`。

---

## 0. 專案定位與頭條主張

本專案將既有的純軟體通訊鏈路模擬器（numpy 浮點 Monte Carlo BER）延伸為一條完整的 **numpy → 定點 golden model → RTL → gate-level PPA** 驗證鏈路，並以此回答一個可證偽的工程問題：

**頭條主張**：總能量 = 發射能量 + 解碼能量。強碼（K=7 soft Viterbi）節省約 5 dB 發射功率，但需支付解碼器功耗；因此存在一個臨界距離 d\*，**低於 d\* 時未編碼傳輸的每交付位元總能量反而較低**。本專案量測 d\* 的位置，以及 LLR 量化位寬（3–6 bits）如何移動 d\*。

**誠實定位**：此 crossover 在低功耗 WSN/BAN 文獻中是已知效應。本專案的貢獻不是發現它，而是用一條**自建、可復現、逐層 bit-accurate 驗證**的鏈路把它重新量出來，並量化「字寬 → d\*」的關係。

**證偽條件（先寫死，不得事後修改）**：在 η_PA ∈ [0.1, 0.5]、2.4 GHz free-space 或 indoor path loss 模型的合理參數範圍內，若 d\* < 1 公尺或不存在，主張即告失敗，報告需如實記載。

---

## 1. 範圍界定

### In scope
- Viterbi 解碼器：K=7, R=1/2, soft-decision，完整三層模型與 co-sim。
- 設計空間掃描：LLR 位寬 Q、clip level、PM 字寬 W、traceback 深度 D、平行度。
- Gate-level PPA（Sky130）與以真實通道資料驅動的功耗估計。
- 總能量模型與 d\* 交叉點分析。

### Out of scope（明確禁止，避免時程失控）
- **LDPC：完全不碰。** 迭代解碼 + layered scheduling + 記憶體子系統是獨立專案規模。
- Polar SC（min-sum f/g，N=256/1024）：**stretch goal**，僅在 Viterbi 全部里程碑（M1–M5）完成後才可開工。
- FPGA 實作：非本專案範圍（CPU 上的 Verilator 模擬算力已足夠，見 §5）。
- 通道編碼理論創新：本專案是量測與驗證方法學，不是新碼設計。

---

## 2. 三層模型架構與比對點

### 2.1 核心定義：「bit-accurate」是什麼、不是什麼

- **Bit-accurate**：在**架構狀態（architectural state）邊界**上完全相等。對 Viterbi 而言，邊界是每一個 trellis stage 結束後的：
  1. Branch metric 向量 `BM[]`
  2. Path metric 向量 `PM[]`（64 個狀態）
  3. Survivor bit 向量（每狀態 1 bit）
- **不要求 cycle-accurate**：RTL 內部如何 pipeline、幾個 cycle 完成一個 stage，是 RTL 自己的事。比對只發生在 stage 邊界。

**最重要的反模式（絕對禁止）**：不得把 golden model 寫成 RTL 的翻譯本（模仿 pipeline、valid/ready、延遲）。那會導致「兩邊錯同一個錯」，驗證失去鑑別力。

### 2.2 三層與兩個比對點

```
L1  浮點參考模型（既有 numpy 鏈路，float64）
 │
 │  C1: 量化損失 —— 以 dB 計價，不是 pass/fail
 ▼
L2  定點 golden model（整數 numpy；GPU 掃描用 CuPy/PyTorch 整數版）
 │
 │  C2: 位元級相等 —— 零容忍，每 stage 比對 BM / PM / survivor
 ▼
L3  RTL（SystemVerilog，Verilator 模擬）
```

| 比對點 | 性質 | 通過標準 |
|---|---|---|
| C1 (L1↔L2) | 計價 | 產出「定點相對浮點的 dB 損失」曲線，作為設計空間 y 軸；不設 pass/fail |
| C2 (L2↔L3) | 零容忍 | 所有測試向量、所有 stage、所有欄位 `np.array_equal` 為真；任一 bit 不同即為 bug |

### 2.3 獨立性規則（工作守則，違反即重做）

1. **L2 必須從 spec（本文件 §3 + 標準教科書演算法）重寫**，撰寫 L2 時不得參考任何 RTL 程式碼。
2. **L2 完成、G1–G4 全綠、測試向量凍結（git tag）之後，才允許開始寫 RTL。**
3. 撰寫 RTL 時可以讀 L2 的**介面定義與測試向量格式**，不得複製 L2 的實作結構。
4. 論文/報告中的所有數字必須來自單一 CSV 資料來源，且每個數字可由 script 重新產生（沿用 RISC-V 專案的慣例）。

---

## 3. Viterbi 設計參數（定案，不得更改）

| 項目 | 設定 |
|---|---|
| 卷積碼 | K=7, R=1/2，生成多項式 (133, 171)₈，d_free = 10 |
| 狀態數 | 64 states = 32 個 radix-2 butterfly（ACS） |
| 調變 | BPSK over AWGN（沿用 L1 既有通道模型） |
| 軟判決量化 Q | {3, 4, 5, 6} bits，均勻量化器 |
| Clip level | 以雜訊標準差 σ 為單位掃描（建議網格：{1.5, 2.0, 2.5, 3.0}σ，可微調） |
| PM 字寬 W | {8, 10, 12} bits，採 **Hekstra modulo normalization** |
| Traceback 深度 D | {24, 32, 48, 64}（理論下限 ≥ 5K = 35；24 預期會壞，留作負向資料點） |
| 平行度 | full-parallel（64 ACS，1 bit/cycle）為主；8-way 與 1-way folded 為 PPA 比較點 |
| Frame 結構 | Terminated：資料 + 6 個 tail bits 歸零；frame 長度 ≥ 1024 info bits |

### 演算法要點（給 L2 與 RTL 共同遵守）

> **修訂 B1**：v1 同時說 branch metric 是「相關度量」（⇒ 取最大）與 ACS 用 `torch.minimum`（⇒ 取最小），
> 兩者矛盾。且 Hekstra modulo normalization 的標準證明要求 branch metric **非負且有界**。
> 改用下列非負距離度量：它與相關度量只差一個每 stage 的常數（在比較中抵銷），
> 決策與 BER 完全相同，但 modulo normalization 變成教科書合法。

- **Branch metric**：以 Q-bit 無號軟值 `r ∈ [0, 2^Q − 1]`：

  ```
  bm(c=0) = r
  bm(c=1) = (2^Q − 1) − r
  BM(branch) = bm(c0) + bm(c1)  ∈ [0, λ_max],   λ_max = 2·(2^Q − 1)
  ```

  全整數運算。`g0=133₈` 與 `g1=171₈` 的 MSB tap 都是 1，故前驅 `p` 與 `p+32` 的碼字**互補**，
  `BM(p+32, u) = λ_max − BM(p, u)`——每個 butterfly 只需一個 branch metric 輸入。

- **ACS**：每 butterfly 做 add-compare-select，**取最小**。比較在 modulo 算術下進行——
  把 `(PM_i − PM_j)` 解讀為 **W-bit 有號數**再取符號，即可在 wraparound 下得到正確比較結果。
  平手（`PM_a == PM_b`）時選 **survivor bit 0**（與 `np.argmin` 一致：回傳第一個最小值）。
  實作上以 `diff = sum_b − sum_a; sel_a = ~diff[W-1]` 一行達成，平手自動落到 A，不需額外比較器。

- **Min-PM state 不能對原始 wrapped `pm[]` 取 argmin**（它們會 wrap）。
  正確做法（L2 / GPU / RTL 三方相同）：`d_s = signed_W(pm[s] − pm[0])`，再對 `d_s` 取 argmin，最低索引勝出。

- **Modulo normalization 正確性條件（G6 不變式）**：見 `docs/wordlength_bound.md`。
  **修訂 B2**：v1 的條件漏掉初始化。正確條件為 `2^(W−1) > 14·(2^Q − 1) + 1`
  （含 `PM_INIT = 6·λ_max + 1`）。12 個 (Q,W) 格點中有 4 個先驗不安全——它們就是 G6 的天然負向測試。

- **Traceback**：memory traceback（sliding-window，深度 D）。每 stage 從 **min-PM state** 起追；
  frame 尾端利用 termination 從 state 0 沖出。**輸出延遲 2D–3D stages**（v1 寫「= D」是錯的）。
  完整定義見 `docs/traceback_convention.md`。

---

## 4. 驗證策略：兩層 testbench

### Tier A — cocotb（功能驗證，10⁴–10⁵ bits）

- Python testbench，**直接 import L2 golden model**，同一份 numpy 程式碼驅動 DUT 與參考——不經過檔案匯出。
- 每個 trellis stage 結束時，從 DUT 拉出 `BM[]`、`PM[]`、survivor bits，執行：
  ```python
  assert np.array_equal(dut_pm, golden.pm), f"PM mismatch @ stage {t}"
  ```
- 測試向量組成：
  1. 定向測試：全零、全一、單一 impulse、已知碼字 + 特定錯誤模式（1-bit、2-bit、burst）。
  2. 約束隨機：隨機資料 × 隨機 SNR ∈ [0, 8] dB × 每個 (Q, W, D) 組態。
  3. 邊界測試：故意觸發 PM 接近 wraparound 的低 SNR 長 frame。
- **目的**：功能 bug 幾乎全在此層抓到，debug 迴圈以秒計。

### Tier B — Verilator + C++ harness（**修訂**：它的目的不是量 BER）

> **修訂**：v1 要求「C++ 端的 AWGN + 量化器必須與 L2 位元級一致」。這在工程上做不到
> （numpy 的 PCG64 + ziggurat 與任何 C++ RNG 都不可能逐位元組相同，除非共用實作）。
> **這個要求應該被廢除，而不是放寬。**

**C++ harness 沒有 RNG，也沒有量化器。** 它只重播 L2 匯出的激勵：

```
scripts/gen_stimulus.py (L2/GPU) → stimulus_Q4_snr3.0.bin   # packed Q-bit 軟值
                                 → expected_Q4_snr3.0.bits   # packed 解碼位元
                                 → manifest.json             # 兩者的 SHA-256 + seed + 全部參數
tb/cpp/sim_main.cpp              # 讀 stimulus、驅動 DUT、與 expected XOR、數 mismatch
```

零容忍、串流、沒有「兩份實作要逐位元組相同」的問題，而且**比 10⁵-bit 等價比對更強**：
Tier-B 的激勵**就是** L2 的激勵，逐位元組相同，附雜湊 manifest。
吞吐量無虞：10⁸ bits × 2 symbols × 4 bits = 100 MB，Verilator 約 3 MHz ⇒ 33 s ⇒ 3 MB/s 的讀取。
AWGN 的統計驗證（經驗變異數 vs N0/2）留在 `golden/` 內，不進 C++。

**Tier B 真正的用途**：C2 已證明 RTL ≡ golden 逐位元相等，
所以 **RTL 的 BER 曲線與 L2/GPU 的 BER 曲線在數學上是同一條**。
重跑 10⁸-bit 的 Verilator Monte Carlo 去「重新量」一條已知的曲線不是驗證，是算術。
這是方法學上的**強項**，不是抄捷徑——報告應直接寫：

> 我們不量 RTL 的 BER。我們證明 RTL ≡ golden 逐位元相等，然後在 golden 上以 100× 的樣本數量 BER。

Tier B 的三個真實任務：

1. **C2 延伸浸泡**：把輸入空間擴大 4 個數量級，但方式是**繼續比對**（只比解碼位元，
   1 bit/stage，幾乎免費），不是量 BER。以 **frame 邊界**對齊（frame 已 terminated），不靠 cycle 延遲。
2. **Assertion 浸泡**：G6 的 wraparound 是稀有事件。在低 SNR 下跑 10⁸ stages，
   才是這個哨兵真正發揮價值的地方。
3. **長跑控制 FSM 穩健性**（數千次 frame 邊界與 reset）。

規模因此從 384 runs 收縮到 **≈24**（3 winner × 8 SNR）。每個 10⁸ cycles @ 2–5 MHz ⇒ 20–50 s；
12 個並行 process ⇒ 約 2 分鐘。瓶頸反而移到**激勵產生**，故激勵用 GPU/批次 L2 產生。

BER 曲線本身（到 10⁻⁶）由 L2/GPU 提供，error count < 100 的資料點標註信賴區間——
用既有模擬器的 `cluster_robust_ci`（它已針對 Viterbi 的叢發錯誤調校，實測 var_inflation ≈ 2.03）。

### 平行化策略（重要）

- **正確做法**：跨（組態 × SNR 點）開獨立 process，各 run 完全獨立。
- **錯誤做法**：Verilator `--threads`——對 64-state 這種小設計幫助有限，不要依賴它。

---

## 5. 硬體預算與 CPU/GPU 分工

### 目標機器
- CPU：AMD Ryzen 7 9700X（8C/16T）
- GPU：NVIDIA GeForce RTX 5070（Blackwell，**sm_120，需 CUDA 12.8+**；CuPy/PyTorch 需對應新版，否則會出現 "no kernel image available"。**環境設置的第一步是跑一個最小整數 kernel 驗證 GPU 可用。**）

### 算力估算（已驗算，作為排程依據）

- Verilator 對此規模設計的模擬速率估 2–5 MHz；full-parallel Viterbi 為 1 bit/cycle。
- 單一 (SNR 點 × 組態) 跑 10⁸ bits：`10⁸ ÷ 3×10⁶ ≈ 33 秒`（單執行緒）。
- **修訂 B6**：v1 寫「8 SNR × 4 Q × 3 W × 4 D ≈ 384 runs」——**漏掉了 clip 軸**（4 個值）。
  GPU 的全網格是 `4 Q × 4 clip × 3 W × 4 D × ~10 SNR ≈ 1920 點`。
- RTL 端不跑全網格：見 §4 的修訂，Tier B 收縮到 **≈24 runs**（3 winner × 8 SNR），
  且它的目的不是量 BER 而是延伸 C2 浸泡。約 2 分鐘。
- **結論：RTL Monte Carlo 在 CPU 上完全可行，不需要 FPGA。**

### 分工

| 資源 | 任務 |
|---|---|
| **GPU（L2 掃描）** | 粗掃整個 (Q, clip, W, D) × SNR 網格。Viterbi 在 trellis 方向序列、**跨 frame 完全平行**：batch 數千 frame，用 CuPy/PyTorch 整數運算實作 ACS（`torch.minimum` + 索引選擇即 compare-select）。目的：找出 BER floor 位置與有意思的區域。 |
| **CPU（L3 確認）** | 僅對 GPU 掃描選出的 **3–5 組 winner 組態**做 RTL 位元級驗證（Tier A）與 BER 確認（Tier B）。 |

---

## 6. Known-answer test 閘門（G1–G6）

所有閘門必須自動化（單一指令可重跑），結果寫入 `data/gates.csv`。這是本專案對外宣稱正確性的依據。

| Gate | 已知答案 | 驗證對象 | 容差 |
|---|---|---|---|
| Gate | 已知答案 | 驗證對象 | 容差 | M1 實測 |
|---|---|---|---|---|
| E1–E3 | 環境（見 §9 M0） | 工具鏈 | 已於 M0 全綠 | 綠 |
| G1 | 未編碼 BPSK，BER = 10⁻⁵ 需 Eb/N0 = 9.588 dB | L1/L2 通道模型與 AWGN scaling | ±0.1 dB | **9.571 dB** |
| **G2a** | 實測 soft BER 不得**顯著**超出 (133,171) 的 union bound | 解碼器演算法 | **零容忍（對顯著性）** | 最大 實測/界 = **0.981** |
| **G2b** | 未量化 + D=64 參考組態下，@1e-5 對未編碼的增益 | 解碼器演算法 | **[5.0, 5.6] dB** | **5.434 dB** |
| G3 | 3-bit 軟判決 vs 無限精度，**在掃描網格中最佳 clip 下**損失 ≈ 0.2 dB | 量化器設計 | ±0.15 dB | **0.225 dB**（clip 2.5σ） |
| **G4a** | 實測 hard BER 不得**顯著**超出硬判決 union bound | Branch metric | **零容忍（對顯著性）** | 最大 實測/界 = **1.034** |
| **G4b** | 硬判決 vs 軟判決的損失 | Branch metric | **[2.2, 2.7] dB**（**事後修正**） | **2.413 dB** |
| G5 = C2 | L2 vs L3 位元級相等：每 stage 比對 `bm[4]`、`pm[64]`、`survivor[64]`、**解碼位元** | RTL 正確性 | **零容忍** | M3 |
| G6 | Modulo **決策等價**（見下） | 字寬選擇 | **零容忍**（安全格點）；4 個不安全格點須觸發 | 4/4 觸發（M1 向量） |
| **G7** | 雙模擬器一致性（Verilator 2-state vs Icarus 4-state） | reset 完整性 | **零容忍** | M3 |
| **C2′** | L2-CPU vs L2-GPU 位元級相等 | GPU golden model | **零容忍** | M2 |

> **修訂 B3'（G4，事後修正，2026-07-14）。強度弱於 G2 的事前修正，如實標示。**
>
> v1 的 G4 是「硬判決損失 ≈ 2 dB ±0.3」，即 [1.7, 2.3]。但**硬判決的 union bound
> ——一條定理，由已與文獻核對過的重量分布算出，完全獨立於本專案的任何量測——
> 給出的損失是 2.355 dB，本身就落在那個區間之外**。也就是說：任何正確的解碼器都不可能
> 通過 v1 的 G4。容差本身是錯的（「≈2 dB」是經驗法則；硬判決的漸近指數只有軟判決的一半，
> 漸近損失是 10·log10(2) = 3.01 dB，1e-5 落在非漸近區，2–3 dB 才是預期）。
>
> G2 的同一個問題我在**開跑前**就抓到並修正了；G4 沒做同一件事，所以是**量測之後**才發現。
> 修正的依據雖然獨立於數據（不是拿數據去配容差），但時序上是事後的。
>
> **另兩處是閘門本身寫錯，一併修正：**
> 1. **截斷過的 union bound 不是上界。** 原本 `d_max=22` 把尾巴丟掉。軟判決的尾巴被 Q 函數
>    壓死（可忽略），但硬判決每項只以 (4p(1−p))^(d/2) 衰減、而 c_d 每兩步成長 6.6 倍。
>    改用 `d_max=30`（實測 d_max ≥ 26 後變動 < 0.05%）。
> 2. **「違反」的定義改為「95% CI 的下緣超出界」，不是「點估計超出界」。**
>    理由有二：(a) union bound 界的是 **ML** 解碼器，而我們量的是 **D=64 的窗口**解碼器；
>    (b) 拿有雜訊的估計值和一條確定的界做零容忍比較，統計上不成立——在界很緊的高 SNR 區
>    （d_free 主導），一個完全正確的解碼器也會有約一半機率因雜訊而「超出」。
>    實測驗證了這一點：G2a 的最大 實測/界 = 0.981、G4a = 1.034，界確實很緊。

> **修訂 B3（G2）**：v1 的「增益 ≈ 5 dB ±0.3」偏低。(133,171) 的 union bound
> （d_free=10，c_d = 36/211/1404/11633…）給出未量化下 BER 1e-5 落在 Eb/N0 ≈ 4.1–4.35 dB，
> 對未編碼 9.588 dB 的增益 ≈ **5.3–5.5 dB**，落在 [4.7, 5.3] 之外。教科書常引的 5.1–5.2 dB
> 是**實務解碼器**（3-bit soft、D≈35）的值，不是純演算法的值。
> 改為兩段式：G2a 是可證明的硬上界（零容忍），G2b 是明確綁定參考組態的區間。
>
> **修訂（G7 / C2′）**：v1 沒有這兩道。
> G7：Verilator 是 2-state，未初始化的 PM 讀為 0 而非 X，會**靜默隱藏 reset 不完整的 bug**。
> C2′：`torch.minimum` 不回傳索引，GPU 版的 survivor bit 要自己算，`<=` 與 `<` 的選擇會
> **默默決定平手方向**。Q=3 時整數平手很常見，選錯不會報錯，只會讓 C2 在 RTL 上線後噴 mismatch。

### G6 的特殊要求（本專案的「哨兵」）

PM 字寬不足時，wraparound 使比較結果反轉，症狀是**高 SNR 出現神秘 BER floor、低 SNR 完全正常**——這種 bug 靠看 BER 曲線 debug 極慢。本專案的做法：

1. **G6 的定義是「決策等價」，不只是 spread 不等式。** `golden/viterbi_fx.py` 同時維護兩組 PM：
   `pm_mod`（uint，mod 2^W，C2 的比對標的）與 `pm_ref`（int64，無界）。每 stage 斷言
   「由 `pm_mod` 導出的 ACS 選擇與 argmin」等於「由 `pm_ref` 導出的」。**這才是 modulo
   normalization 正確性的證明**；spread 不等式 `|PM_i − PM_j| < 2^(W−1)` 只是一個便宜的
   充分條件，順帶記錄。

2. 實作為 **RTL `always_ff` 內的 immediate assertion**（以 `` `ifndef SYNTHESIS `` 包住）
   + **cocotb 內的等價 check**，每 stage 檢查。
   **修訂 B5**：不用 `bind`、不用 concurrent SVA——Icarus 12/14 不支援 `bind`，
   兩個模擬器都不給可用的 concurrent SVA。原 §8 的 `rtl/sva/pm_invariant.sv` 取消。

3. **負向測試（必做）**：**不需要人工把 W 調到 6**。依 `docs/wordlength_bound.md` 的界，
   規格既有的網格裡就有 4 個先驗不安全的格點：**(Q=4,W=8)、(Q=5,W=8)、(Q=6,W=8)、(Q=6,W=10)**。
   證明 assertion 在 BER floor 於曲線上可見**之前**先觸發。觸發的 stage 與當時的 PM spread 寫入報告。
   另外「實測 Δ_max vs 最壞界 `7·λ_max`」本身就是一張有價值的圖。

---

## 7. PPA 與 energy/bit 方法學

### 流程（**修訂 A2/A3/B4**：不是複用，是從零建置；M0 已驗收通過）

RISC-V 專案的 gate-level power 是 **vectorless** 的（假設 activity=0.2/duty=0.5），
其論文 §9.4 FW4 明列「workload SAIF 的真實-activity EDP」為未竟事項。
**這一段沒有東西可以複用。** 它也從未用過 OpenLane——實際資產是 ORFS Docker image。

M0 已把整條流程建置完成並以一個 8-bit counter 驗收通過（annotation coverage **100%**）：

```
Yosys 0.64（ORFS 容器，階層式，不 flatten）  → gate-level netlist
Icarus 14.0 + sky130 behavioral models      → gate-level VCD（真實 AWGN 輸入向量驅動）
ppa/vcd2saif.py（FIFO 串流，VCD 不落地）     → SAIF
OpenSTA 3.1.0：read_saif -scope tb/dut      → report_activity_annotation + report_power
```

三個非顯而易見、但決定成敗的細節：

1. **SAIF 不能省略。** gate-level VCD 是 **30–180 KB/cycle**；100k cycles = 3–18 GB，
   × 72 個 (組態 × SNR) 點根本放不下。SAIF 是 O(#nets) 而非 O(#nets × cycles)，
   每點 2–10 MB，可入庫當證據。Icarus 不會寫 SAIF，故自寫串流轉換器 `ppa/vcd2saif.py`，
   透過 `mkfifo` 讓 VCD 完全不碰硬碟。

2. **VCD 的 timescale 必須正確解析。** iverilog 把 `$timescale` 寫成**跨行**的。
   單行 regex 比對失敗後若靜默退回預設值，SAIF 的 DURATION 就會差 1000 倍，
   OpenSTA 算出的翻轉密度跟著錯 1000 倍——**而功耗數字看起來仍然像個數字，不會有任何錯誤訊息**。
   （M0 的煙霧測試實際抓到了這個 bug。）

3. **`read_saif -scope` 打錯 = 0% annotation。** SAIF 的根是 testbench（`tb/dut/…`），
   設計的根是 top module。scope 錯了 OpenSTA 不報錯，只會靜靜套用 `set_power_activity`
   的預設猜測——症狀會偽裝成「功耗竟然不隨輸入改變」。
   `report_activity_annotation -report_unannotated` 是這件事的誠實度量，且被
   `ppa/check_annotation.py` 設為硬性 gate（< 90% 直接失敗）。

**硬性要求**：功耗不得用預設 toggle-rate 猜測，必須用**真實通道資料驅動的 switching activity**。並且量測功耗對 SNR 的依賴性（低 SNR → ACS toggle 率高 → 功耗高），此依賴曲線本身是一個交付結果。

### 兩份 netlist，各有用途（**修訂**）

| netlist | 產生方式 | 用途 |
|---|---|---|
| 扁平 | ORFS 預設（`synth -flatten`）+ P&R | 面積、Fmax（post-route STA）、線容上修係數 |
| **階層** | 自寫 `ppa/syn.ys`，**不 flatten** | **功耗 vs SNR、分區塊（ACS vs traceback）拆解** |

**為什麼一定要分區塊回報功耗（本階段最大的風險 R1）**：
D=32 時 survivor 記憶體是 64 states × 3D = **6144 個 flop**，對上 ACS 的 640 個 PM flop
+ 32 個 butterfly——**約 85% 的面積在 traceback 記憶體**。而 traceback 的活動量幾乎與 SNR 無關
（不管 SNR 多少，每個 stage 都寫 64 bits）。後果是：**總功耗對 SNR 的依賴可能只有幾個百分點，
而不是一條曲線**——上面列為交付結果的那條曲線有蒸發的風險。

唯一的救法是把功耗拆成 `P_total / P_ACS / P_traceback`，各自對 SNR 作圖，
證明 SNR 依賴集中在 ACS。這需要階層式 netlist（`report_power -instances [get_cells u_acs]`），
所以功耗路徑**不能** `synth -flatten`。

M0 的 counter 煙霧測試已經看到這個效應的縮影：8 個 flop + 20 個組合 cell 的設計，
功耗是 **Sequential 88.5% / Combinational 11.5%**。

（另註：ORFS image 內含 `sky130_sram_1rw1r_64x256_8`，64 bits × 256 列，
與 survivor 記憶體的形狀正好對得上（3D ≤ 256）。用 SRAM macro 是 M5 的 stretch goal；
主線用 flop 陣列，並在報告中揭露它會**高估**面積與 E_dec、進而高估 d\*。）

### 總能量模型

```
E_total / info bit = E_tx + E_dec
E_tx  = (Eb/N0)_req × N0 × L_path(d) / η_PA
E_dec = P_decoder × T_decode / K_info
```

- `(Eb/N0)_req`：該組態在目標 BER（10⁻⁵）下所需的 Eb/N0，取自 Tier B 量測。
- `L_path(d)`：2.4 GHz free-space 與一組 indoor path loss 模型（雙軸呈現）。
- `η_PA ∈ [0.1, 0.5]` 掃描。
- `P_decoder`：來自 SAIF 流程，分組態、分 SNR。

### 交付圖表

1. BER vs Eb/N0：各 (Q, W, D) 組態 + 未編碼 + 浮點參考。
2. C1 量化損失 dB vs Q（含 clip level 的影響）。
3. E_total vs 距離 d：未編碼 vs Viterbi 各量化組態，標出 d\* 交叉點。
4. d\* vs Q：頭條圖——「字寬如何移動臨界距離」。
5. PPA 表：面積 / Fmax / 功耗（分 SNR）/ energy per info bit，三種平行度。

---

## 8. 建議 repo 結構

```
fec-cosim/
├── docs/
│   ├── fec_viterbi_cosim_spec.md   # 本文件
│   ├── falsification.md            # 證偽條件與事前預測（量測前 commit）
│   ├── energy_model.md             # 能量模型的常數與計價方式（量測前 commit）
│   ├── wordlength_bound.md         # G6 的字寬界 + 安全/不安全格點表        [M1]
│   ├── trellis_convention.md       # 狀態標號、survivor 極性、TIE-BREAK      [M1]
│   ├── traceback_convention.md     # sliding-window 的排程                  [M1]
│   └── report.md                                                            [M6]
├── golden/                 # L2 定點 golden model（先寫、先凍結）
│   ├── viterbi_fx.py       # 整數 numpy：pm_mod + pm_ref 雙軌，mode='window'|'ml'
│   ├── quantizer.py        # LLR 均勻量化器（Q, clip 參數化）
│   ├── invariants.py       # G6 決策等價檢查（L2 端）
│   └── ref_float.py        # L1：K=7 浮點參考（**新寫**，既有模擬器只有 K=3）
├── sweep/
│   ├── viterbi_gpu.py      # CuPy/PyTorch 整數版，跨 frame batch
│   ├── grid_runner.py      # (Q, clip, W, D) × SNR 網格 + 結果彙整
│   └── test_c2prime.py     # C2′：L2-CPU vs L2-GPU 位元級相等
├── rtl/
│   ├── viterbi_defs.svh    # localparams + trellis（用 `include，不用 package）
│   ├── bmu.sv              # branch metric unit
│   ├── acs_butterfly.sv    # radix-2 ACS（modulo 比較）
│   ├── acs_array.sv        # PAR 個 butterfly + PM regfile
│   ├── minpm.sv            # 參考值相減後的 argmin 樹
│   ├── survivor_mem.sv     # 64 bits × 3D 列，環狀
│   ├── traceback.sv
│   ├── ctrl.sv
│   └── viterbi_top.sv      # SYNTHESIS TOP，無 debug port
│                           # （取消 sva/pm_invariant.sv：見修訂 B5）
├── tb/
│   ├── dbg/viterbi_dbg.sv  # XMR debug wrapper，永不進 synth filelist
│   ├── cocotb/             # Tier A：per-stage 比對，import golden/
│   ├── cpp/                # Tier B：無 RNG、無量化器，只重播激勵
│   └── gl/                 # gate-level TB（Icarus）
├── ppa/
│   ├── orfs.sh             # ORFS 容器的 docker run（RISC-V 專案從未記錄過）
│   ├── env.mk              # 容器內的 PDK 路徑常數
│   ├── vcd2saif.py         # 串流 VCD -> SAIF（讓 gate-level 功耗可行的那 150 行）
│   ├── check_annotation.py # annotation coverage 的硬性 gate
│   ├── smoke/              # counter 的全流程煙霧測試（M0 已通過）
│   ├── models/             # vendored sky130 cell models（含 PROVENANCE.md）
│   ├── syn.ys, power.tcl
│   └── out/                # 產物，不入庫
├── data/
│   ├── results.csv         # 唯一資料來源（所有報告數字出自此）
│   ├── gates.csv           # 閘門結果
│   ├── meta_*.json         # 每次 run 的完整 metadata（CLAUDE.md §5.3）
│   └── saif/               # 功耗證據（O(#nets)，可入庫）
├── scripts/                # env.sh, gates.py, m0_gate.py, gen_stimulus.py,
│                           # check_paper_numbers.py …
├── Makefile                # make env / gates / sweep / ber / ppa / report
├── CHANGELOG.md
└── CLAUDE.md
```

---

## 9. 里程碑與驗收標準（5–6 週，與其他專案並行）

> **修訂**：v1 缺 M0，且 5–6 週偏樂觀。務實估計 **8–10 週**（兼職）。

| 里程碑 | 內容 | 驗收標準（全部達成才算完成） |
|---|---|---|
| **M0（週 0）** | **環境建置與工具鏈驗證**（v1 沒有這一段） | E1 Verilator 5.051 + Icarus 14.0（oss-cad-suite，免 root）；E2 sm_120 整數 ACS 與 numpy 逐位元組相等（含平手情形）；E3 **gate-level 功耗流程打通，annotation coverage ≥ 99%**。**已於 2026-07-14 全綠。** |
| **M1（週 1–2）** | L2 定點 golden model + **K=7 浮點參考**（新寫） | G1、G2a、G2b、G3、G4 全綠；C1 損失曲線產出；`windowed(D) − ML` 的 dB 差產出；測試向量凍結並打 git tag；三份凍結文件（trellis / traceback / wordlength）commit。**此時 RTL 一行都不存在。** |
| **M2（週 2–3）** | GPU 掃描 | **C2′ 零 mismatch**；(Q, clip, W, D) × SNR 全網格（≈1920 點）掃完；選出 3–5 組 winner 並記錄選擇理由。 |
| **M3（週 3–5）** | RTL + Tier A | cocotb per-stage 比對打通；winner 組態全部 C2 零 mismatch；定向 + 約束隨機 + 折疊架構 + **G6 負向測試（4 個不安全格點）** + **G7** 全綠。 |
| **M4（週 5–6）** | Tier B + G6 浸泡 | 激勵 manifest 的 SHA-256 對帳 + 解碼位元 XOR 零 mismatch；G6 assertion 在 10⁸ stages 的低 SNR 浸泡下不誤觸發。 |
| **M5（週 6–8）** | PPA + 能量模型 | Sky130 合成收斂；SAIF 功耗**分 SNR、分區塊（ACS vs traceback）**產出；功耗收斂圖；d\* 圖完成；`docs/falsification.md` 的三條條件逐一裁決（成立或不成立，如實記錄）。 |
| **M6（週 8–10）** | 報告 | `data/results.csv` 為唯一來源；`check_paper_numbers.py` 回報 `mismatches: 0`；與既有通訊模擬器的 Pareto 前緣圖接上。 |

**（M6 之後，選配）** Polar SC stretch goal 才允許開工。

---

## 10. Definition of Done

專案完成的定義是以下**全部**成立：

1. G1–G6 全綠，`gates.csv` 有完整記錄（含 G6 負向測試證據）。
2. C2 通過統計可對外宣稱（格式：「N 個測試向量 × M 個 stage 比對，0 mismatch」）。
3. Winner 組態的 BER 曲線到 10⁻⁶，含信賴區間標註。
4. d\* 分析完成，證偽條件已裁決。
5. 所有圖表數字可由 `scripts/` 一鍵重生。
6. 一句話結論成形，格式：「在 2.4 GHz、η_PA = ___ 的鏈路上，K=7 soft Viterbi 的總能量優勢只在 d > d\* = ___ 時成立；Q 從 3 bits 增至 5 bits 使 d\* 從 ___ 移到 ___。」

---

## 11. Coding agent 工作守則（每次開工前重讀）

1. **順序不可顛倒**：L2 → 凍結 → RTL。違反即重做。
2. **L2 與 RTL 保持實作獨立**：寫其中一邊時不讀另一邊的實作碼。
3. **不擴大範圍**：LDPC 禁止；Polar 在 M6 前禁止；FPGA 不在範圍內。
4. **數字紀律**：任何進入報告的數字，必須存在於 `data/results.csv` 且有對應的重生 script。
5. **遇到規格衝突或模糊**：停下來提問，不自行假設。
6. **每個里程碑結束**：跑一次 `make gates`，確認沒有 regression 才進入下一階段。
