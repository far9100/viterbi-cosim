<!--
  thesis.md — 碩士論文整併草稿(單一檔)。
  用途:把 docs/ 分散的 report.md 與五份凍結慣例/能量/證偽文件、spec 需求,
        整併成一份結構完整的碩士論文草稿。本檔為新增的整併產物;
        原始 report.md 與凍結文件一律保留不動,作為 provenance。
  紀律:正體中文為主;每個數字逐字沿用 data/*.csv 既有真值(經 report.md 已稽核),
        受 scripts/check_paper_numbers.py 稽核;架構狀態名一律 bm / pm / survivor;不使用勾叉等狀態符號。
  狀態:Phase B–E 已填入(整併現有材料 + 補寫可支撐章節 + 接圖 + 文獻/參考書目骨架)。
        仍待使用者提供:論文題目、誌謝、英文摘要核定、文獻回顧與參考書目之實際引用。
-->

# 位元精確的 FEC 驗證鏈路與總能量臨界距離：K=7 Viterbi 解碼器的 numpy → 定點 → RTL → Sky130 量測

> **本檔為整併草稿。** 內容整併自 `docs/report.md` 與五份凍結文件(`trellis_convention.md`、
> `wordlength_bound.md`、`traceback_convention.md`、`energy_model.md`、`falsification.md`)及 spec;
> 原始文件保留不動作為凍結證據。標記 `[待補引用]` 與 `[待填]` 處需使用者提供內容。

---

## 前置頁面

### 書名頁

`[待填]` 校名、系所、論文題目、研究生、指導教授、口試委員、學位別、年月。

### 誌謝

`[待填]` 由使用者撰寫。

### 中文摘要

本文把一條純軟體的通訊鏈路模擬器延伸為 **numpy → 定點 golden model → RTL → gate-level PPA** 的位元精確驗證鏈路(K=7, R=1/2, (133,171)₈, 軟判決 Viterbi),並用它回答一個純軟體模擬答不出來的問題:**解碼器的字寬會把「編碼划算的臨界距離 d\*」推到哪裡去。**

三個主要結果:

1. **d\* 存在且遠大於 1 m**(最小 **17.8 m**),三條**預先登記**的證偽條件全部不觸發。其中「同一組 RTL、同一組功耗量測,在兩個能量模型下 d\* 對 Q 的**斜率符號相反**」這條事前預測**確認成立**:模型 A **+11.29%**、模型 B **−0.75%**(自由空間)。
2. **但我對解碼器能量組成的事前估計錯了 3.4 倍**(登記 α ≈ 0.15,實測 **α = 0.517**)。錯因有二,都可量測:traceback 佔 **67.7–84.1% 的 flop** 卻只佔 **43.0–54.2% 的功耗**;而我**完全漏掉了 min-PM 的 argmin 樹**——它佔 **10.3–13.5% 的功耗**、**11.8–19.7% 的面積**,**比整個 PM register file 還大 2.21–2.45 倍**。
3. **規格書要求的「功耗 vs SNR 依賴曲線」被實測推翻,我們把它換成機制。** 總功耗在 1→5 dB 只變動 **1.0%**。原因不是「被 traceback 稀釋」,而是**整條資料路徑的位元活動被隨機資訊源釘在最大熵**:對稱量化器把 BPSK 的兩個假設映到**位元互補**的碼(`r1 = ~r0`),而倖存者位元**就是資訊位元本身**(`u[t−6]`)。**倖存者翻轉率對 SNR 的 R² = 0.000。** 反事實(打破位元互補性)使效應**回來**,證明機制成立。

關鍵詞:`[待補]` 前向錯誤更正、Viterbi 解碼、定點驗證、位元精確協同模擬、臨界距離、低功耗。

### 英文摘要 Abstract

`[初稿,待使用者核定]`

This thesis extends a pure-software communication-link simulator into a bit-exact verification chain **numpy → fixed-point golden model → RTL → gate-level PPA** for a K=7, R=1/2, (133,171)₈ soft-decision Viterbi decoder, and uses it to answer a question that pure-software simulation cannot: **how the decoder's word length moves the critical distance d\* beyond which channel coding becomes energy-worthwhile.** Three results follow. (1) **d\* exists and is far larger than 1 m** (minimum **17.8 m**); all three pre-registered falsification conditions fail to trigger, and the pre-registered prediction that d\*'s slope with respect to Q has **opposite sign** under two energy models is confirmed (model A **+11.29%**, model B **−0.75%**, free space). (2) The a-priori estimate of the decoder-energy composition was **wrong by 3.4×** (registered α ≈ 0.15, measured **α = 0.517**), for two measurable reasons: traceback consumes 67.7–84.1% of the flops but only 43.0–54.2% of the power, and the min-PM argmin tree — overlooked entirely — costs 10.3–13.5% of power and is 2.21–2.45× larger than the whole PM register file. (3) The spec-required "power-versus-SNR" curve is **refuted and replaced by a mechanism**: total power varies only **1.0%** over 1→5 dB, because a symmetric quantizer maps the two BPSK hypotheses to bit-complementary codes and the survivor bit is the information bit itself, pinning datapath activity at maximum entropy (survivor toggle-rate vs SNR **R² = 0.000**); a counterfactual restores the effect, confirming the mechanism.

Keywords: `[待補]` forward error correction, Viterbi decoding, fixed-point verification, bit-exact co-simulation, critical distance, low power.

### 目錄 / 圖目錄 / 表目錄

`[待產生]` Markdown 階段先留佔位;轉學校模板(LaTeX/Word)時自動生成。

### 符號與縮寫表

**設計參數(定案,不得更改)**

| 符號 | 意義 | 值 / 範圍 |
|---|---|---|
| K | 約束長度 constraint length | 7 |
| R | 碼率 code rate | 1/2 |
| (133,171)₈ | 生成多項式 generator polynomials | 八進位 |
| d_free | 自由距離 free distance | 10 |
| — | 狀態數 / butterfly 數 | 64 states / 32 radix-2 butterflies |
| Q | 軟判決量化位元數 | {3, 4, 5, 6} bits |
| clip | 量化截斷位準(以雜訊 σ 為單位) | {1.5, 2.0, 2.5, 3.0}σ |
| W | 路徑度量字寬 path-metric word width | {8, 10, 12} bits |
| D | traceback 深度 | {24, 32, 48, 64}(理論下限 ≥ 5K = 35) |
| — | 幀結構 | 終止碼:資料 + 6 個 tail bits;幀長 ≥ 1024 info bits |

**架構狀態訊號(golden / rtl / tb 命名一致)**

| 符號 | 意義 |
|---|---|
| bm | 分支度量 branch metric |
| pm | 路徑度量 path metric(`pm_mod` = mod-2^W 無號、`pm_ref` = 無界 int64 雙軌) |
| survivor | 倖存者位元 survivor bit |
| λ_max | 最大分支度量 = 2·(2^Q − 1) |
| PM_INIT | 路徑度量初始值 = 6·λ_max + 1 |
| G6 安全條件 | 2^(W−1) > 14·(2^Q−1) + 1 |

**能量與通道模型**

| 符號 | 意義 | 值 |
|---|---|---|
| d\* | 總能量臨界距離 critical distance | 量測結果(最小 17.8 m) |
| α | 解碼器能量對 Q 的縮放係數 | 登記 0.15、實測 0.517 |
| η_PA | 功率放大器效率 | [0.1, 0.5] |
| N0 / NF | 雜訊功率譜密度 / 雜訊指數 | NF = 6 dB;N0 = 1.5940e-20 J |
| f_c / λ | 載波頻率 / 波長 | 2.4 GHz / 0.124913 m |
| n | path-loss 指數 | {2.0 自由空間, 3.5 室內} |
| R_s | 符號率 | 1 Msym/s |
| P_circuit | 收發電路功耗 | 60 mW |
| f_clk | 解碼器時脈 | 100 MHz |
| E_tx / E_dec / E_total | 傳輸 / 解碼 / 總能量(每 info bit) | — |
| Model A / Model B | 只算 PA+解碼器 / 加計電路功耗 | — |

**驗證層、比較點與 Gate**

| 符號 | 意義 |
|---|---|
| L1 / L2 / L3 | numpy 浮點參考 / 定點 golden model / SystemVerilog RTL |
| C1 | L1↔L2 量化損失(以 dB 計價,非 pass/fail) |
| C2 / C2′ | L2↔L3 位元級相等 / L2-CPU↔L2-GPU 位元級相等(零容忍) |
| Tier A / Tier B | cocotb 逐 stage 比對 / Verilator C++ 大量浸泡 |
| E1–E3 | M0 環境 gate |
| G1–G4 | 通訊層已知答案 gate(BPSK、編碼增益、量化損失、硬判決損失) |
| G5 | = C2,RTL 位元級正確 |
| G6 | modulo 決策等價(字寬選擇的哨兵) |
| G7 | 雙模擬器一致性(Verilator 2-state vs Icarus 4-state) |
| F1–F3 | 三條預先登記的證偽條件 |

**縮寫**

FEC 前向錯誤更正;ACS add-compare-select;BPSK / AWGN;LLR 對數似然比;SAIF / PPA / PDK / RTL;
ML 最大似然;KAT known-answer test;WSN / BAN 無線感測 / 體域網路;SVA SystemVerilog assertion;
ADC / FoM 類比數位轉換器 / 品質因數;STA / DRV 靜態時序分析 / 設計規則違反。

---

## 第 1 章 緒論

### 1.1 研究背景與動機

在短距離、電池供電的無線鏈路(無線感測網路 WSN、體域網路 BAN)裡,一則訊息送達接收端所耗的總能量,並不只有天線發射出去的那一份。它由兩部分組成:

```
每交付一個資訊位元的總能量 = 發射能量 E_tx + 解碼能量 E_dec
```

強通道編碼(如本文的 K=7 軟判決 Viterbi)能提供約 5 dB 的編碼增益,讓發射端在相同的錯誤率下少送好幾倍的功率,因此**壓低 E_tx**。但天下沒有白吃的午餐:要享受這個增益,接收端必須跑一台不算便宜的解碼器,而它要耗電——**墊高 E_dec**。

發射能量 `E_tx` 隨傳輸距離 `d` 以 `d^n`(n 為路徑損耗指數)成長,解碼能量 `E_dec` 卻與距離無關。於是必然存在一個**臨界距離 d\***:短於 d\* 時,省下的發射能量還不夠付解碼器的電費,**不編碼反而每位元總能量更低**;長於 d\* 時,編碼才開始划算。這個交叉點在低功耗 WSN/BAN 文獻中是已知效應,本文的目的不是「發現」它,而是用一條**自建、可重現、逐層位元精確**的驗證鏈路把它**量到底**,並回答一個純軟體模擬回答不了的問題。

### 1.2 問題陳述

純軟體的浮點模擬可以算出編碼增益與 BER,卻算不出 `E_dec`——因為解碼能量是硬體的性質,取決於資料路徑的字寬、切換活動與製程。本文的核心研究問題是:

> **軟判決量化字寬(Q 從 3 到 6 bit)會把臨界距離 d\* 推到哪裡去?**

要回答它,必須把浮點模型一路做到閘級功耗量測,而且每一層之間都要能對得起來(否則 E_dec 的數字無法被信任)。

為了讓結論可被證偽,本文採**預先登記**(pre-registration)的作法:在任何能量量測開跑之前,先把證偽條件與事前預測寫進 `docs/falsification.md` 並提交(commit 時間戳可驗證早於量測)。規格書原本的證偽條件是「若 d\* < 1 m 或不存在,主張即失敗」,但這條實質上不可能觸發(交叉點在數學上必然存在,且量級遠大於 1 m)。因此本文保留原條件之餘,追加兩條真正咬得住、指向本文貢獻的條件(見 §4.6)。

### 1.3 研究貢獻

本文的貢獻可條列為四點:

1. **一條自建、可重現、逐層位元精確的驗證鏈路方法。** 從 numpy 浮點參考(L1)、定點 golden model(L2)、到 SystemVerilog RTL 與 Sky130 閘級(L3),層與層之間以零容忍的位元級相等(C2)扣合,並以 30 個已知答案 gate 與一鍵冷啟動重現(`make repro`,逐位元相同)保證每個數字可追溯、可重生。
2. **d\* 與「字寬如何移動 d\*」的預先登記量測。** d\* 存在且遠大於 1 m(最小 17.8 m);三條預先登記證偽條件全部存活;「d\* 對 Q 的斜率在兩個能量模型下符號相反」這條最咬得住的事前預測確認成立。
3. **一次誠實的事後檢討。** 對解碼器能量組成的事前點估計 α 錯了 3.4 倍(登記 0.15、實測 0.517),本文如實記錄兩個可量測的錯因,並指出公式與符號推理仍成立、被推翻的只有點估計。
4. **一個負面結果與其機制。** 規格書要求的「功耗 vs SNR」曲線被實測推翻,本文把這個 null 轉成一條機制:編碼後的訊號被白化,使解碼器資料路徑的位元活動與 SNR 無關,並以反事實與跨層量測交叉驗證。

### 1.4 論文組織

第 2 章鋪陳背景與理論(卷積碼、Viterbi/ACS、軟判決量化、定點正規化、總能量模型)。第 3 章文獻回顧。第 4 章方法論,說明三層驗證架構、四份凍結慣例、能量計價與證偽設計。第 5 章實作。第 6 章結果。第 7 章討論。第 8 章結論與未來工作。

---

## 第 2 章 背景與理論

<!-- 來源: trellis_convention.md, wordlength_bound.md, traceback_convention.md, energy_model.md -->

### 2.1 卷積碼與 K=7 (133,171) 碼

卷積碼以一組生成多項式把輸入位元串流編成輸出串流。本文採用約束長度 K = 7(記憶元 m = K−1 = 6,故有 64 個狀態)、碼率 R = 1/2、生成多項式為八進位 (133, 171)₈ 的碼;其自由距離 d_free = 10(由廣度優先搜尋驗證)。

多項式以八進位給定,最高位對應當前輸入 `u_t`、最低位對應最舊的 `u_{t−6}`:

```
g0 = 133₈ = 0b1011011  ⇒  c0 = u_t ^ u_{t−2} ^ u_{t−3} ^ u_{t−5} ^ u_{t−6}
g1 = 171₈ = 0b1111001  ⇒  c1 = u_t ^ u_{t−1} ^ u_{t−2} ^ u_{t−3} ^ u_{t−6}
```

每個輸入位元產生 2 個編碼位元(碼率 1/2)。本文採終止碼(terminated):資料後接 6 個 tail bits 把編碼器逼回狀態 0,幀長 ≥ 1024 個資訊位元。

### 2.2 Viterbi 解碼與 ACS butterfly

Viterbi 是卷積碼的最大似然序列解碼器。它在 trellis 上為每個狀態維護一個路徑度量(path metric)`pm`,每個 stage 對每個狀態做 add-compare-select(ACS):把前驅狀態的 `pm` 加上分支度量(branch metric)`bm`,比較兩條進入路徑,選較佳者,並記下選擇(survivor bit)。

64 個狀態可組織成 32 個 radix-2 butterfly。狀態的次態律為 `s' = ((s << 1) | u) & 0x3F`(新輸入從最低位進入),於是狀態 `s = j` 與 `s = j+32` 這一對,經過一步都落到同一對次態 `{2j, 2j+1}` 上——這就是一個 butterfly。本碼滿足兩條互補性(見 §4.2),使得每個 butterfly 只需要一個分支度量輸入,是 radix-2 ACS 的標準結構。

解碼的最後一步是 traceback:從路徑度量最小的狀態往回追,還原出被送出的資訊位元。

### 2.3 軟判決量化

硬判決把接收樣本先切成 0/1 再解碼,軟判決則保留量化後的可靠度資訊餵給解碼器,可換回約 2 dB。本文以 Q-bit 無號軟值 `r ∈ [0, 2^Q−1]` 表示(r 小代表傾向碼位元 0),分支度量定義為相關距離:

```
bm(c=0) = r,   bm(c=1) = (2^Q − 1) − r
BM(碼字 c) = bm(c0) + bm(c1) ∈ [0, λ_max],   λ_max = 2·(2^Q − 1)
```

量化器由兩個參數界定:位元數 Q ∈ {3,4,5,6} 與截斷位準 clip ∈ {1.5,2.0,2.5,3.0}σ(以雜訊標準差為單位)。量化帶來的損失以 dB 計價(比較點 C1),成為設計空間的一個座標軸,而非 pass/fail 判準。

### 2.4 定點運算與 modulo(Hekstra)正規化

在硬體裡路徑度量會單調累加而溢位。Hekstra 的 modulo 正規化利用一個事實:只要任兩狀態的路徑度量差恆小於 `2^(W−1)`,就可以讓 `pm` 在 W-bit 無號數裡自由 wraparound,而 ACS 的比較改用模數運算(把差值解讀為 W-bit 有號數),結果仍正確——因此不需要任何顯式的減常數正規化步驟。

要讓這招成立,W 必須夠大。本文推導出安全條件(見 §4.3):

```
2^(W−1) > 14·(2^Q − 1) + 1
```

並指出 spread 的最大值出現在 stage 1(初始化那一項),而非穩態;初始化須取 `PM_INIT = 6·λ_max + 1`。這使得 12 個 (Q,W) 格點裡有 4 個先驗不安全,負向測試不必人工製造(見 §6.3)。

### 2.5 總能量模型與臨界距離概念

每交付一個資訊位元的總能量為:

```
E_total = E_tx + E_dec           (模型 A,規格書原模型)
E_total = E_tx + E_dec + P_circuit · T_air   (模型 B,WSN 文獻標準)
其中  E_tx = (Eb/N0)_req · N0 · L(d) / η_PA,   E_dec = P_decoder / f_clk
```

路徑損耗以 1 m 為參考點:`L(d) = (4π/λ)² · d^n = 1.01174e4 · d^n`(1 m 處 40.05 dB)。模型 A 只算功率放大器與解碼器;模型 B 再加上收發電路功耗——在固定符號率下,R=1/2 的編碼鏈路要付兩倍空中時間、兩倍電路能量(預設 60 nJ/info bit),這一項比 E_dec(約 0.1 nJ 級)大 600 倍,是低功耗文獻裡「短距離下編碼不划算」的真正機制。臨界距離 d\* 就是使 `E_total(編碼) = E_total(未編碼)` 的那個 d(詳見 §4.5)。

---

## 第 3 章 文獻回顧

`[本章為骨架,實際引用待使用者提供;不捏造書目。]`

### 3.1 通道編碼的能量取捨與臨界距離

短距鏈路「編碼是否划算」的能量取捨,以及把收發電路功耗計入的能量模型(本文的模型 B),源自低功耗 WSN/BAN 文獻。`[待補引用:Cui, Goldsmith, Bahai — energy-constrained modulation and coding]`

### 3.2 Viterbi 解碼器硬體與效能界

Viterbi 演算法、其軟/硬判決效能,以及本文用來當 gate 的 union bound。`[待補引用:Viterbi 原始論文;Heller & Jacobs — Viterbi decoding performance]`

### 3.3 定點字寬與 modulo 正規化

路徑度量的 modulo(Hekstra)正規化與字寬選擇。`[待補引用:Hekstra — modulo normalization for Viterbi decoders]`

### 3.4 ADC 能量模型

軟判決所需 ADC 的能量,以品質因數(FoM)估計。`[待補引用:Walden — ADC survey / figure of merit]`

---

## 第 4 章 方法論

### 4.1 三層驗證架構 L1/L2/L3 與比較點 C1/C2

<!-- 來源: report.md §1 -->

驗證鏈路由三層與兩個比較點組成:

```
L1  numpy 浮點參考(K=7 ML Viterbi)
     │  C1:量化損失,以 dB 計價(不是 bug,是設計代價)
L2  定點 golden model(Q, W, D 參數化;modulo normalization)
     │  C2:位元級相等,零容忍
L3  SystemVerilog RTL → Sky130 gate-level
```

**C1** 衡量從浮點到定點的量化損失,以 dB 計價,成為設計空間的座標軸。**C2** 是零容忍的位元級相等:每個 stage 都比對 `bm[4]`、`pm[64]`、`survivor[64]`,**以及解碼位元**,任何一個位元不同即為 bug。

把解碼位元納入比對集是關鍵。M3 曾發生:`traceback` 被餵了打拍後(上一個 stage)的 survivor,而 register exchange 需要這個 stage 的;症狀極陰險——`bm`/`pm`/`survivor`/`best` 全部完全正確,只有 256 個解碼位元裡錯 3 個(位置 0、254、255),因為高 SNR 下存活路徑收斂得很快。全零向量完全測不出來,是全一向量露出來的。只比 `bm`/`pm`/`survivor` 的 C2 會讓這個 bug 完整通過。

一個推論:**本文不量 RTL 的 BER。** C2 已證明 RTL ≡ golden 逐位元相等,兩條 BER 曲線在數學上是同一條;重跑上億位元去「重新量」一條已知曲線不是驗證,是算術。BER 一律在 golden 上量(樣本數多 100×)。

### 4.2 Trellis 慣例與 ACS butterfly

<!-- 來源: trellis_convention.md -->

三方(L2、GPU-L2、RTL)都從同一份凍結的 trellis 慣例實作,任一方的狀態標號、survivor 極性或 tie-break 不符,C2 就會噴出看似隨機的位元錯誤。凍結的重點:

- **次態與 butterfly**:`s' = ((s<<1)|u)&0x3F`;butterfly `j ∈ [0,31]` 吃 `PM[j]`、`PM[j+32]`,吐 `PM[2j]`、`PM[2j+1]`。
- **Survivor 極性**:`survivor[s']=0` 代表前驅是 `s'>>1`,`=1` 代表 `(s'>>1)+32`。
- **Tie-break**:`PM_a == PM_b` 時選 survivor bit 0(對應 `np.argmin` 取第一個最小值)。三方須採同一規則:numpy 用 `np.argmin` 自然符合;torch 因 `torch.minimum` 不回索引須寫 `sel_a = (sum_a <= sum_b)`(用 `<=`);RTL 用 `diff = sum_b − sum_a; sel_a = ~diff[W−1]`(減法方向刻意是 b−a,使平手時 `sel_a=1`,省一個等於比較器)。Q=3 時整數平手很常見,M0 的 GPU 煙霧測試刻意斷言「平手樣本數 > 0」以確保這條語意被測到。

本碼滿足兩條互補性:P1(`c(s,u=1)=~c(s,u=0)`,條件為每個多項式的 MSB=1)與 P2(`c(p+32,u)=~c(p,u)`,條件為每個多項式為奇數/LSB=1)。配合 `bm(c)+bm(c^3)=λ_max`,可推得每個 butterfly 只需一個分支度量輸入。**RTL 不得匯入 L2 的 trellis 表**,必須從八進位多項式在 elaboration 時自行推導,以避免 common-mode 錯誤(兩邊錯同一個錯,C2 對它盲目);RTL 端加一個 KAT 把推導出的表與手算表 diff。

### 4.3 字寬界與 G6 決策等價

<!-- 來源: wordlength_bound.md -->

Modulo 正規化要正確,任兩狀態的路徑度量差(在無 wraparound 的參考算術下)必須小於 `2^(W−1)`。PM spread 的最大值出現在 stage 1(可達狀態的 PM ≤ λ_max,其餘 ∈ [PM_INIT, PM_INIT+λ_max]),因此綁住整體的是初始化項,得安全條件:

```
2^(W−1) > 7·λ_max + 1 = 14·(2^Q − 1) + 1
```

這揭露 spec v1 的一個錯誤:若採「顯而易見」的 `PM_INIT = 2^(W−1)−1`,連安全格點都會在 stage 1 誤觸發 assertion。

更重要的是,**G6 的定義是「決策等價」,不只是 spread 不等式**。`golden/viterbi_fx.py` 同時維護 `pm_mod`(uint,mod 2^W,C2 的比對標的)與 `pm_ref`(int64,無界,G6 的參考),每個 stage 斷言「由 `pm_mod` 導出的 ACS 選擇與 argmin == 由 `pm_ref` 導出的」。spread 不等式只是一個便宜的充分條件,順帶記錄下來。取 min-PM 狀態時不能對 wrapped 的 `pm_mod` 直接 argmin,須以狀態 0 為參考相減、解讀為 W-bit 有號數再取最小。

### 4.4 Traceback 架構

<!-- 來源: traceback_convention.md -->

C2 只比對 `bm`/`pm`/`survivor` 是不夠的:traceback 策略不同會產生不同的解碼位元、不同的 BER,卻完全通得過那樣的 C2——所以解碼位元也被納入 C2(G5),其語意必須先凍結。本文的凍結策略是 **uniform depth D 的 sliding window**:每個 stage 從 min-PM 狀態往回追固定 D 步、輸出 1 個位元,使每個位元的有效回溯深度都恰好是 D(這是「traceback depth D」的教科書定義,也是讓 D 軸有意義的唯一寫法);尾端 D−1 個位元利用終止狀態精確回溯沖出。

> **D 軸的實測只解析得出一件事,本文不作更強的宣稱。** `data/d_sweep.csv` 的「windowed(D) − ML」損失為 D=24: +0.209 dB、D=32: −0.050 dB、D=48: +0.058 dB、D=64: −0.072 dB。只有 D=24(低於理論下限 5K = 35)那一項是解析得出的;D=32/48/64 三者不但**非單調**,而且出現**負損失**——窗口回溯贏過全幀 ML,數學上不可能——顯示這三點全部落在量測雜訊地板(±0.076 dB,由 C1 的負損失幅度估得)之內。因此本文只宣稱「D 低於 5K 會可觀變差」,**不宣稱 D=64 優於 D=32**。另有 `mode='ml'` 全幀回溯作對照組,提供「windowed(D) − ML」的免費設計空間資料點。

這排除了教科書常見的 one-pointer 批次 traceback(有效深度落在 [D,2D])。能在 1 bit/cycle 下達成 uniform depth D 的自然選擇是 **register exchange**(64 個狀態各持一個 D-bit 暫存器,每 stage 全改寫;面積 64×D flop,比 memory traceback 的 64×3D bits 小,但翻轉率與功耗高)。RTL 不論選哪種,解碼位元都必須與此語意逐位元相同;實際輸出延遲為 D 個 stage。

### 4.5 總能量模型的計價方式

<!-- 來源: energy_model.md -->

能量模型的所有常數在任何量測開跑之前凍結於 `docs/energy_model.md`(物理常數 k、T₀、c、f_c、λ;系統參數 NF=6 dB、N0=k·T₀·F、η_PA∈[0.1,0.5]、n∈{2.0,3.5}、R_s=1 Msym/s、P_circuit=60 mW、f_clk=100 MHz、目標 BER=1e-5)。M5 的 script 只讀本文件的參數,不得在程式碼裡另立數值。

其中最關鍵、規格書卻漏掉的一項是**固定符號率 vs 固定資訊率**。本文採固定符號率 R_s = 1 Msym/s,故 R=1/2 的編碼鏈路每個 info bit 花 2 個符號、2 µs 空中時間,比未編碼多付 `P_circuit × 1/R_s = 60 nJ/info bit` 的電路能量。這一項在模型 B 裡是支配項(比 E_dec 大 600 倍),使 d\* 相差兩個數量級。`E_dec = P_decoder / f_clk`(full-parallel 為 1 info bit/cycle),並假設解碼器在 frame 之間被 power-gated(工作週期僅 0.5%);為了任何 f_clk 都能重算,`data/results.csv` 分開記錄 `e_dyn_per_bit` 與 `p_leak`。

模型明訂四項須揭露的計價偏差:survivor 用 flop 陣列而非 SRAM macro(高估 E_dec ⇒ d\* 為上界)、ADC 能量未計入(附 Walden FoM 敏感度線)、編碼器/slicer 能量可忽略、glitch 功率為近似。

### 4.6 預先登記與證偽設計

<!-- 來源: falsification.md §0–§4 -->

證偽條件與事前預測在任何能量量測開跑之前提交(`docs/falsification.md`,commit 時間戳可驗證早於量測,實測早 21.2 小時)。規格書 §0 的原條件(d\* < 1 m)實質不可能觸發,故本文保留它之餘追加兩條:

- **F1(沿用規格書)**:在 η_PA ∈ [0.1,0.5]、2.4 GHz free-space/indoor 的合理範圍內,若 d\* < 1 m 或不存在,主張失敗。事前預測:不觸發(事前估計 d\* 落在 13.7 m–5.4 km)。
- **F2(針對頭條貢獻)**:若 Q 從 3 增至 6 使 d\* 的變動在兩個模型下皆小於 5%,則「字寬移動臨界距離」的貢獻宣稱失敗。
- **F3(針對本文自己的事前推理)**:若 d\* 對 Q 的變動在模型 A 下超過 30%,或變動符號與預測相反(模型 A 應正、模型 B 應負),則事前機制推理被推翻。

事前機制:Q 增加時,量化損失變小使編碼增益變大(d\* 變小)與 PM 字寬變大使 E_dec 變大(d\* 變大)方向相反。令 α 為 E_dec 中隨 W 縮放的比例,`E_dec(Q=6)/E_dec(Q=3) = 1 + 0.5α`。本文事前登記 α ≈ 0.15(survivor 記憶體支配),得模型 A 約 +2.8%/+1.6%(自由空間/室內);模型 B 因 60 nJ 電路能量淹沒 E_dec 變化,得 −0.87%/−0.50%。**最咬得住的一條是:同一組 RTL、同一組功耗量測,d\* 對 Q 的斜率在兩個模型下符號相反**(裁決見 §6.7 與第 7 章)。

### 4.7 已知答案 gate 體系與稽核紀律

<!-- 來源: report.md §1, spec §6 -->

驗證以已知答案 gate 自動化(一鍵一命令,寫入 `data/gates.csv`),共 36 筆(30 個有判準的 gate + 6 筆觀測):M0 環境 3、M1 golden 6、M2 掃描 3、M3 RTL 5、M4 浸泡 3、M5 PPA 8、M9 低功耗基準線 8。gate 的已知答案來自閉式解或效能界(如 union bound),而非事後湊出的數字(G2、G4 的判準均在量測前依 union bound 修正過,見 §6.1)。

稽核紀律:每個出現在報告裡的數字都由 `data/*.csv` 現算,`scripts/check_paper_numbers.py` 對每個被引用的數字同時驗兩件事——(a) 它等於 CSV 算出的真值;(b) 那個字串確實出現在文中(防止斷言與文件脫節)——`mismatches: 0` 才准提交。整條鏈路可由 `make repro` 冷啟動重建,除時間戳外逐位元相同。

---

## 第 5 章 實作

<!-- 來源: golden/ rtl/ sweep/ tb/ ppa/ 結構 + traceback_convention §5, trellis_convention §8 -->

### 5.1 L2 定點 golden model

L2 是驗證鏈路的「記錄基準」,以整數 numpy 實作,由 `golden/` 下的模組組成:`viterbi_fx.py`(定點 Viterbi:分支度量 `bm`、雙軌路徑度量 `pm_mod`/`pm_ref`、survivor、`argmin_modulo`、逐 stage history 匯出)、`quantizer.py`(由 Q、clip 參數化的均勻量化器,含 `lambda_max`、`pm_init`)、`trellis.py`(由生成多項式推導 trellis)、`traceback.py`(`window`/`ml` 兩模式)、`bounds.py`(卷積碼權重分佈與 union bound,G2a/G4a 的 oracle)、`ref_float.py`(L1 浮點參考)、`ber.py`(蒙地卡羅 BER)。

### 5.2 GPU 設計空間掃描

為在合理時間內掃完 (Q,clip,W,D)×SNR 的網格,`sweep/` 以 torch int32 實作跨幀批次的 ACS(`viterbi_gpu.py`),survivor 打包成兩個 int32、tie-break 用顯式 key `d*64+idx`(不依賴 `torch.argmin` 的未定義行為)。C2′(`test_c2prime.py`)驗證 L2-CPU 與 L2-GPU 位元級相等(零容忍),`grid_runner.py` 做可續跑的網格掃描與 winner 選擇。

### 5.3 RTL 架構

`rtl/` 為 full-parallel(PAR=32)decoder:`viterbi_top.sv`(合成 top,含 G6 即時 assertion 哨兵,以無界 `pm_ref` 做決策等價)、`bmu.sv`(分支度量)、`acs_array.sv`(32 butterfly + PM register file)、`acs_butterfly.sv`(radix-2 ACS)、`minpm.sv`(modulo 下的 min-PM)、`traceback.sv`(register exchange,固定深度 D)、`ctrl.sv`(幀控制 FSM);`viterbi_defs.svh` 由八進位多項式推導 trellis 與編碼器,刻意不從 L2 匯入。架構狀態訊號在 RTL 端為 `bm`/`pm`/`survivor`(對應 `bm_pk`/`pm_pk`/`surv_pk`)。

### 5.4 Tier A(cocotb)與 Tier B(Verilator C++)驗證平台

**Tier A**(`tb/cocotb/`)直接匯入 L2 golden,於每個 `stage_done` 逐 stage 比對 `bm[4]`/`pm[64]`/`survivor[64]`/解碼位元,涵蓋 directed(全零/全一/impulse/已知碼字加錯)、constrained-random 與邊界(逼近 wraparound)測試。**Tier B**(`tb/cpp/sim_main.cpp`)是 Verilator C++ 浸泡平台,無 RNG、無量化器,只重放 L2 匯出的 stimulus(bin + expected.bits + SHA-256 manifest),用以把 C2 推到上億位元。另有 file-driven SV 平台跑 Icarus 4-state 交叉檢查(G7)。

### 5.5 Sky130 PPA 與 SAIF 功耗流程

`ppa/` 自建閘級功耗流程(零 RISC-V 重用):Yosys 合成 → OpenSTA(含 OpenROAD `repair_design`)量 Fmax → 以真實 AWGN 通道資料驅動的 gate-level switching activity 算功耗 → VCD 轉 SAIF → 分區塊(ACS vs traceback)分 SNR 統計。annotation coverage 100% 為 gate 條件;SAIF 以 gzip 壓縮 + SHA-256 manifest 歸檔並驗證可逐位元重算。

---

## 第 6 章 結果

### 6.1 通訊層結果(BER、編碼增益、量化損失)

<!-- 來源: report.md §1.1 -->

| 量 | 實測 | 判準 |
|---|---|---|
| 未編碼 BPSK @ 1e-5 | **9.571 dB** | 9.588 dB ± 0.1 |
| 編碼增益 @ 1e-5(未量化、D=64) | **5.434 dB** | [5.0, 5.6] dB |
| 3-bit 軟判決損失(最佳 clip = 2.5σ) | **0.225 dB** | 0.20 ± 0.15 |
| 硬判決損失 | **2.413 dB** | [2.2, 2.7] dB |
| 軟/硬判決 BER vs union bound | 最大 實測/界 = **0.981 / 1.034** | 無顯著違反 |

其中 G2(編碼增益)與 G4(硬判決損失)的判準都在量測前依 union bound 修正過:v1 的「增益 ≈ 5 dB ±0.3」與「硬判決損失 ≈ 2 dB ±0.3」被證明與 union bound 矛盾(硬判決界本身即 2.355 dB,落在 [1.7,2.3] 之外),故分別改為 G2a/G2b 與 G4a/G4b。

![圖 6.1:各組態 BER vs Eb/N0(含未編碼與浮點參考)](../figures/fig_ber_m1.png)

![圖 6.2:M2 全網格 BER](../figures/fig_m2_grid.png)

![圖 6.3:C1 量化損失 dB vs Q(含 clip level)](../figures/fig_c1_loss.png)

![圖 6.4:traceback 深度 D 對 BER 的影響](../figures/fig_d_sweep.png)

### 6.2 C2 位元精確等價

<!-- 來源: report.md §1 -->

| 里程碑 | 規模 | 結果 |
|---|---|---|
| C2(Tier A) | 32 組 (Q,W,D) / 86 frames / **22,532 個 stage** | **0 mismatch** |
| C2(Tier B 浸泡) | 12 個點 / **245,760,000 個資訊位元** / 247,200,000 個 stage | **0 mismatch** |

每個 stage 比對 `bm[4]`、`pm[64]`、`survivor[64]` 以及解碼位元(見 §4.1 的 bug 故事)。C2′(L2-CPU vs L2-GPU)亦零 mismatch,期間實測 85,072 個 ACS 平手樣本,確認 tie-break 語意被真正測到。

### 6.3 設計空間塌縮與 winner 選擇

<!-- 來源: report.md §1.1, wordlength_bound.md §4 -->

**設計空間從 (Q, clip, W, D) 塌成 (Q, clip, D)**:W 不是 BER 的軸。這是 G6(modulo 決策等價)的推論,並由 C2′ 直接比對解碼位元驗證,不是假設。每個 Q 的最小安全 W 由字寬界唯一決定(3→8, 4→10, 5→10, 6→12),PPA 上沒有選擇餘地。

字寬界也讓 G6 的負向測試不必人工製造:12 個 (Q,W) 格點中有 4 個先驗不安全——(Q=4,W=8)、(Q=5,W=8)、(Q=6,W=8)、(Q=6,W=10)。實測這些不安全格點在低 SNR 下 **BER 不降反升**(安全組態下降 2.58 decades;(Q=6,W=8)/(Q=5,W=8) 被釘在 BER=0.5)。

M2 從 winner 中選出 4 個作 RTL 標的(不用合成的成本分數):最佳 BER(Q6/clip3.0/W12/D64,需 4.1522 dB)、最小記憶體(Q6/W12/D32,4.1937 dB)、最小 Q/ADC(Q4/W10/D64,4.1909 dB)、教科書對照(Q3/clip2.0/W8/D32,4.3593 dB)。

> **前三者之間的排序在統計上沒有被解析出來,選擇理由因此是結構性的、不是 BER 的。** 三者所需 Eb/N0 的全距只有 0.0415 dB,而量測雜訊地板約 ±0.076 dB——`data/c1_quantization_loss.csv` 有 6 個格點被標記 `below_noise_floor`,其中出現物理上不可能的**負**量化損失(Q6/clip2.0 為 −0.0761 dB),雜訊地板即由此估得。所以「Q6/D64 是 BER 最佳」只在點估計的意義上成立,與 Q4/D64、Q6/D32 之間是平手。四個組態被選中的真正理由是它們**張開了 PPA 的設計空間**(最小 D、最小 Q、教科書基準),而非它們的 BER 排名。與 Q3(4.3593 dB)的差距 0.166 dB 則遠大於雜訊地板,是唯一被解析出來的 Q 效應——它也正是 §6.5 的 Δd\* 所依據的那一項。

![圖 6.5:不安全字寬導致的 BER floor](../figures/fig_m2_ber_floor.png)

### 6.4 PPA 與功耗

<!-- 來源: report.md §2 -->

功耗由真實 AWGN 通道資料驅動的 gate-level switching activity 算出,8 個點的 SAIF annotation coverage 全部 100%。@ 3 dB、100 MHz:

| 組態 | 需 Eb/N0 | P_total | E_dec | traceback | ACS | min-PM |
|---|---|---|---|---|---|---|
| Q3 W8 D32 | 4.3593 dB | **24.090 mW** | **240.9 pJ/bit** | 13.055 (54.2%) | 8.146 (33.8%) | 2.482 (10.3%) |
| Q6 W12 D32 | 4.1937 dB | **30.321 mW** | **303.2 pJ/bit** | 13.044 (43.0%) | 12.597 (41.5%) | 4.081 (13.5%) |
| Q4 W10 D64 | 4.1909 dB | 44.077 mW | 440.8 pJ/bit | 29.525 | 11.103 | 3.012 |
| Q6 W12 D64 | 4.1522 dB | 46.964 mW | 469.6 pJ/bit | 29.221 | 13.167 | 3.981 |

同一個 D=32 下,traceback 功耗為 13.055 vs 13.044 mW(只差 0.08%)——register exchange 的活動量確實與 Q、與資料無關;Q 的差異全落在 ACS(+54.7%)與 min-PM(+64.4%)。

一個意外發現:**min-PM 的 argmin 樹比整個 PM register file 還大**(2.21–2.45×,佔總面積 11.8–19.7%),這是選 best-state 而非 fixed-state traceback 的直接代價。

Fmax 方面,直接對 Yosys netlist 跑 OpenSTA 得 166.81 ns(6.0 MHz),但關鍵路徑是一顆最小反相器驅動 8683 個 sink、18.10 pF、中間無 buffer tree——這是流程缺口(`abc` 只做技術映射、不插 buffer),非架構極限。跑 OpenROAD `repair_design` 後四個組態皆 ≥ **101.2 MHz > 100 MHz**,能量模型的 f_clk 假設站得住;因 `E = α·C·V²` 與頻率無關,此步不影響功耗/面積/d\*。

### 6.5 臨界距離 d\* 與字寬

<!-- 來源: report.md §3.1–§3.2 -->

d\*(3 dB 功耗,η_PA = 0.1):

| 組態 | A / 自由空間 | A / 室內 | B / 自由空間 | B / 室內 |
|---|---|---|---|---|
| Q3 D32 | 153.6 m | **17.8 m** | 2428.7 m | 86.0 m |
| Q6 D32 | 170.9 m | 18.9 m | 2410.6 m | 85.6 m |
| Q4 D64 | 206.1 m | 21.0 m | 2413.0 m | 85.7 m |
| Q6 D64 | 212.3 m | 21.4 m | 2409.2 m | 85.6 m |

三條預先登記證偽條件的裁決:

| 條件 | 判準 | 實測 | 裁決 |
|---|---|---|---|
| F1 | d\* < 1 m 或不存在 ⇒ 主張失敗 | 最小 d\* = **17.8 m** | 不觸發 → 存活 |
| F2 | 兩模型下 \|Δd\*\| 皆 < 5% ⇒ 貢獻宣稱失敗 | 模型 A **+11.29% / +6.31%** | 不觸發 → 存活 |
| F3 | A 為負、或 B 為正、或 \|A\| > 30% ⇒ 事前推理被推翻 | A **正**、B **負**、A < 30% | 不觸發 |

**符號翻轉確認成立**(比較 Q3/D32 與 Q6/D32,同一個 D、完全相同的 traceback):

| | 事前登記 | 實測 |
|---|---|---|
| 模型 A(自由空間 / 室內) | +2.8% / +1.6% | **+11.29% / +6.31%** |
| 模型 B(自由空間 / 室內) | **−0.87% / −0.50%** | **−0.75% / −0.43%** |

模型 B 的量級幾乎完全命中。機制:Q 增加時量化增益(d\* 變小)與解碼器能量(d\* 變大)方向相反;模型 B 的 60 nJ 電路能量淹沒 E_dec 變化,只剩量化增益,故符號翻轉。ADC 能量(敏感度線,非量測)與 E_dec 同向,只會加大 Δd\*、不會翻轉符號,使 F2 的結論更穩。

![圖 6.6:E_total vs 距離 d,標出 d\* 交叉點](../figures/fig_m5_dstar.png)

![圖 6.7:d\* vs Q(頭條圖)](../figures/fig_m5_dstar_q.png)

規格書 §9 的 M6 驗收條件要求「與既有通訊模擬器的 Pareto 前緣圖接上」,此圖為該項的交付(先前遺漏)。左圖以 survivor 記憶體 64×3D 位元為**面積代理**涵蓋全部 64 個網格點(附 95% CI 誤差棒),右圖以 gate-level SAIF **量測**的 E_dec 涵蓋僅有的 4 個合成組態。兩軸刻意分開:代理指標不是能量,而面積與能量在本設計裡並非同一件事(§6.4:traceback 佔 67.7–84.1% 的 flop 卻只佔 43.0–54.2% 的功耗)。

![圖 6.10:Pareto 前緣 —— 通訊效能 vs 硬體成本](../figures/fig_pareto.png)

### 6.6 負面結果:功耗 vs SNR 與白化機制

<!-- 來源: report.md §4 -->

規格書 §7 把「功耗對 SNR 的依賴曲線(低 SNR → ACS toggle 率高 → 功耗高)」列為交付結果。**實測:總功耗在 1→5 dB 只變動 1.0%,非單調,方向與前提相反**;分區塊也救不了它(連 ACS 的 switching 都只變 1.8%)。這不是被 traceback 稀釋。**用詞的界線(M9 之後修正)**:先前寫的是「效應本來就不存在」,那句話強於資料所能支撐。M9 補上 8 個獨立 seed 的 null 分布後才檢定得出:σ_null = 0.1415 mW、斜率 +0.0814 mW/dB、t = +1.82,95% 區間跨過零 ⇒ 斜率與零無法區分,但那不等於零。正確的敘述是「效應被侷限在累加器、僅佔約 1% 總功耗,本量測解析不出」——不能說它不存在,也沒有證據說它存在。

機制:量化器對稱,`r(c=1) = (2^Q−1) − r(c=0) = ~r`,把 BPSK 兩個假設映到位元互補的碼;編碼位元 i.i.d. uniform,故翻轉率 ≈ 0.5、與 SNR 無關。狀態遞迴使「狀態 s' 的正確 survivor bit」= `u_{t−6}`(資訊位元本身),所以一個完美的與一個完全失效的 Viterbi,其 survivor 記憶體切換活動一模一樣。線性迴歸證實(5 個點的「看起來單調」不是證據,R² 才是):唯一有系統性趨勢的是路徑度量 `pm`(累加器,R²=0.913),而 `survivor` 對 SNR 的 R²=0.000;PM+min-PM 只佔 ~7–13% 的功耗,故 pm 的 3.3% 稀釋到總功耗只剩 ~1%。

反事實:加一個整數 DC offset(真實 ADC 的比較器偏移)打破 `r1=~r0`,則受影響位元的翻轉率從 0.5042 崩到 0.0000,定律 `toggle(k)=0.5·1{bit k 在兩個 rail 上相異}` 精確成立——效應回來,機制成立。跨層驗證:numpy golden(演算法)與 Sky130 SAIF(硬體)兩條獨立路徑對倖存者翻轉率的預測吻合到 1% 以內(如 1 dB:golden 0.4664 vs SAIF 0.4661),證明機制在演算法裡、不在 RTL 裡。推論(超出本專案):任何接收編碼(白化)訊號的解碼器,其資料路徑活動都與 SNR 無關——編碼的作用本來就是白化。

![圖 6.8:功耗 vs SNR(負面結果)](../figures/fig_m5_power_snr.png)

![圖 6.9:各訊號的翻轉率 vs SNR](../figures/fig_m5_toggle.png)

### 6.7 證偽條件裁決總表

<!-- 來源: falsification.md §5;與 §6.5 對照,不重貼數值表 -->

三條證偽條件(F1/F2/F3)的裁決數值已列於 §6.5。彙整而言:三條全部不觸發,d\* 主張與「字寬移動臨界距離」的貢獻宣稱皆存活,且事前的符號推理獲實測支持。此裁決以 `data/gates.csv`、`data/results_m5_power.csv`、`data/results_m5_dstar.csv` 為依據,可由 `python3 scripts/m5_gate.py` 完整重生;預先登記文件的 commit 時間戳實測早於量測 21.2 小時(git 可驗證)。裁決未涵蓋的事項(不得默示為已驗證)見 §7.3。

---

## 第 7 章 討論

### 7.1 α 事後檢討

<!-- 來源: report.md §3.3, falsification.md §5.2 -->

事前登記的 α ≈ 0.15,實測 `E_dec(Q=6)/E_dec(Q=3) = 303.21/240.90 = 1.2586 ⇒ α = 0.517`,差了 3.4 倍。兩個錯誤都可量測:

1. **用 flop 數去估功耗佔比。** 面積上 traceback 確實佔 67.7–84.1% 的 flop,但功耗只佔 43.0–54.2%——ACS 與 min-PM 有大量組合邏輯(加法器、比較器、argmin 樹),燒 switching power 但不是 flop。
2. **完全漏掉 min-PM 的 argmin 樹。** α 的定義是「ACS + PM 暫存器 + BMU」,根本沒把它列進去;而它隨 W 縮放(2.482→4.081 mW,+64.4%,超線性),佔 10.3–13.5% 的功耗。

誠實的補充:`falsification.md §3.2` 的表本來就列了 α=0.50 那一列(+10.8%/+6.1%),而實測(α=0.517)正好落在那裡(+11.29%/+6.31%)。**公式與符號推理都通過了檢驗,被推翻的只有點估計。** 一個漂亮旁證:同一個 D 下 traceback 功耗只差 0.08%,證明誤差不在 traceback 項,而在「隨 W 縮放那一塊」被我估得太小。

### 7.2 機制的跨層驗證意義

<!-- 來源: report.md §4.3–§4.4 -->

負面結果之所以可信,在於它同時被兩條完全獨立的路徑證實:numpy golden(演算法層)預測的倖存者翻轉率,與 Sky130 gate-level SAIF(硬體層)量到的,逐點吻合到 1% 以內,連 4 dB 那個非單調的凹陷兩邊都有。這說明「資料路徑活動與 SNR 無關」是演算法的性質、不是某個 RTL 寫法的偶然。其推論超出本設計:編碼即白化,任何解碼編碼訊號的資料路徑功耗都不隨 SNR 變——規格書的前提隱含假設了「SNR 會改變位元統計」,但 SNR 只改變位元的正確性,而 switching power 只看統計。

### 7.3 誠實的界線與限制

<!-- 來源: report.md §5, energy_model.md §6, falsification.md §5.4 -->

本文明確揭露以下未驗證或有偏差的項目,不得默示為已驗證:

1. **d\* 的絕對值是上界,而 Δd\* 是下界——兩個偏差方向相反。** survivor 記憶體用 flop 陣列而非 SRAM macro,高估面積與 E_dec ⇒ 高估 d\*。

   本文先前寫「Q 之間的相對比較不受影響(同一 D 下 traceback 完全相同,實測差 0.08%)」,**該推論的方向反了**:Δd\* 由 `Δln(E_dec)` 驅動,而 traceback 正是 E_dec 裡**與 Q 無關**的那一項;一個與 Q 無關的大常數加在分子上會把 `E_dec(Q6)/E_dec(Q3)` 往 1 拉,也就是**稀釋** Q 依賴性。「traceback 完全相同」正是它**會**影響相對比較的理由。把 traceback 功耗乘上縮減因子(模擬換成 SRAM;**敏感度線,非量測值**,見第 5 項未做):係數 1.0 / 0.5 / 0.2 / 0.1 對應 E_dec 比值 1.2586 / 1.3551 / 1.4572 / 1.5056,Δd\*(模型 A、室內)為 +6.31% / +8.57% / +10.85% / +11.89%。方向明確:flop 陣列高估 traceback ⇒ **低估 Δd\***,故 §6.5 的 +11.29% / +6.31% 是**下界**。F2 的裁決不受影響(縮減只會讓 Δd\* 更遠離 5% 門檻),F3 的符號亦不受影響(模型 B 的 Δd\* 由 60 nJ 電路能量支配,與 traceback 無關)。見 `data/results_m5_tb_sensitivity.csv`。
2. **Fmax 是 post-placement / pre-route**,無真實繞線寄生、無 clock tree,`repair_design` 只修 DRV;真實 Fmax 會更低。PPA 表的面積/功耗取自修復前 netlist,buffer tree 讓面積增加約 3%,功耗增量未量測。
3. **ADC 能量是敏感度線,不是量測值。**
4. **glitch 功率是近似**(gate-level 採 `-DFUNCTIONAL -DUNIT_DELAY`,非 SDF 標註延遲)。
5. **PPA 表只涵蓋 full-parallel(PAR=32)。** 折疊架構(PAR=8/1)、post-route P&R、memory traceback 對照、SRAM macro 版本都沒做。

5b. **只有 4 個組態被合成過**:(Q3,W8,D32)、(Q6,W12,D32)、(Q4,W10,D64)、(Q6,W12,D64)。**Q=5 從未合成**,D=32 上也沒有 Q=4/Q=5 的點。因此 §6.5 的「d\* vs Q」在 D=32 上**只有兩個資料點**,中間那條線是連線、不是擬合;64 個網格點裡只有 4 個有量到的能量,其餘 60 個不得外插(見圖 6.10)。

5c. **Tier A 的 frame 長度是 256,不是規格書 §3 凍結的「≥ 1024 info bits」。** M1 凍結的測試向量即為 256-bit frame(22,532 stages / 86 frames = 262 = 256 + 6)。Tier B 用的是 1024(20,000 frames × 1,024 bits,0 mismatch),故「≥ 1024」在**解碼位元**層級已被涵蓋;未被涵蓋的是 1024-bit frame 下的 per-stage `bm`/`pm`/`survivor` 比對。**刻意不以重新產生凍結向量來消除這項不符**——向量已在 tag `m1-golden` 凍結並帶 SHA-256,為了讓事後發現的不符看起來消失而改動凍結物,會毀掉凍結本身的意義。

5d. **沒有與任何已發表的 Viterbi 解碼器或 d\* 數字做過對照,本文不含 baseline 比較表。** 已知的直接前案是 Howard, Schlegel, Iniewski(EURASIP JWCN 2006),其臨界距離分析涵蓋多個解碼器實作(含類比)、跨環境與寬頻率範圍,**覆蓋面廣於本文**;本文相對它的增量只在「解碼器能量來自逐位元驗證過的 RTL + 真實通道驅動的 SAIF」這一點。
6. **機制曾試錯四輪**(其中兩輪是實驗設計寫壞,非機制錯),全部保留在 `scripts/diag_mechanism.py` 的 docstring;核心主張四輪都沒被打破。

---

## 第 8 章 結論與未來工作

### 8.1 結論

本文以一條自建、逐層位元精確、可一鍵冷啟動重現的驗證鏈路,把 K=7 軟判決 Viterbi 解碼器從 numpy 浮點一路量到 Sky130 閘級,回答了純軟體模擬回答不了的問題。結論可濃縮為:在 2.4 GHz、η_PA = 0.1 的鏈路上,編碼要在約 **17.8 m** 之外才划算;把軟判決從 3 bit 加到 6 bit 會把這個距離往外推 6.3%(室內,模型 A)——但若把收發電路功耗算進去(模型 B),它反而往內縮 0.43%。**符號會翻**,這是事前就登記的預測,並獲實測確認。至於「功耗會隨 SNR 變」——**效應被侷限在累加器、僅佔約 1% 總功耗,本量測解析不出**(t = 1.82),因為編碼過的訊號是白的,而 switching power 只看統計、不看資訊。此外,本文如實記錄了一次事前點估計錯 3.4 倍的檢討,並指出公式與符號推理仍成立。

### 8.2 未來工作

- **折疊架構的 PPA:** 現只做 full-parallel(PAR=32),PAR=8/1 折疊版可補上面積/功耗/吞吐的取捨。
- **SRAM macro survivor memory:** 以 `sky130_sram_1rw1r_64x256_8` 取代 flop 陣列,可把 d\* 從上界收緊為實測。
- **post-route P&R 與真實 Fmax:** 補上繞線寄生、clock tree 與 setup 最佳化,給出可信的最高頻率。
- **memory traceback 對照:** 與 register exchange 做完整 PPA 比較。
- **Polar SC(stretch goal):** spec 規定須在 M6 之後、經書面確認才可開工;LDPC 明文禁止。

---

## 參考文獻

`[待補引用:待使用者提供引用清單,依學校格式編排;不捏造書目]`

種子引用(僅記人名/主題,待補完整書目):

- Cui, Goldsmith, Bahai — energy-constrained modulation and coding(能量取捨、模型 B)。
- Viterbi;Heller & Jacobs — Viterbi 解碼與 union bound。
- Hekstra — modulo normalization。
- Walden — ADC survey / FoM。

---

## 附錄

### 附錄 A：Trellis 手算 KAT 表

<!-- 來源: trellis_convention.md §7 -->

| s | u | s' = (s<<1\|u)&63 | c0 | c1 |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |
| 0 | 1 | 1 | 1 | 1 |
| 1 | 0 | 2 | 0 | 1 |
| 1 | 1 | 3 | 1 | 0 |
| 2 | 0 | 4 | 1 | 1 |
| 2 | 1 | 5 | 0 | 0 |
| 3 | 0 | 6 | 1 | 0 |
| 3 | 1 | 7 | 0 | 1 |

前 4 個 butterfly:

| j | 吃 | 吐 | c(j,0) | c(j+32,0) |
|---|---|---|---|---|
| 0 | PM[0], PM[32] | PM[0], PM[1] | 00 | 11 |
| 1 | PM[1], PM[33] | PM[2], PM[3] | 01 | 10 |
| 2 | PM[2], PM[34] | PM[4], PM[5] | 11 | 00 |
| 3 | PM[3], PM[35] | PM[6], PM[7] | 10 | 01 |

### 附錄 B：凍結文件與 git tag 對照

<!-- 來源: git tag, docs/ 凍結檔 -->

| tag | 里程碑 | 對應凍結證據 |
|---|---|---|
| m0-env | 環境 + 閘級功耗流程 | — |
| m1-golden | L2 golden 凍結 | `trellis_convention.md`、`traceback_convention.md`、`wordlength_bound.md`;46 個 C2 測試向量 + SHA-256 |
| m2-sweep | GPU 掃描 | C2′ 零 mismatch;280 點網格 |
| m3-rtl | RTL + Tier A | C2 22,532 stage 零 mismatch |
| m4-tierb | Tier B 浸泡 | 247.2M stage 零 mismatch |
| m5-ppa | PPA + 能量 + 證偽 | `energy_model.md`、`falsification.md`(§5 裁決) |
| m6-report | 報告 + 數字稽核 | `check_paper_numbers.py` mismatches: 0 |
| m7-repro | 冷啟動重現 | `make repro` 逐位元相同 |
| v1.0 | 專案定案 | spec §10 六項 Definition of Done 全達成 |

### 附錄 C：重現步驟

<!-- 來源: energy_model.md §7, README.md, make repro -->

環境為 WSL2 Ubuntu 24.04。安裝(`setup_venv.sh` / `setup_eda.sh` / `setup_gpu.sh` / `setup_models.sh`)後,以 Makefile 逐里程碑重建:`make env / m1 / m2 / m3 / m4 / m5 / figures / report`。`make repro` 為冷啟動驗證:刪除 `data/`(含 GPU `cache_m2`)後從頭重建,`git status` 須顯示除 `meta_*.json` 外每個 CSV 與 SAIF 皆逐位元相同。每個報告數字都可由 `scripts/` 下的腳本從 `data/*.csv` 重算,`make report` 機械化此稽核(對值正確性與字串出現同時檢查)。

### 附錄 D：36 筆 gate 記錄完整清單

<!-- 來源: data/gates.csv;數值見 §6 各表,此處為索引 -->

M0(3):E1 Verilator+Icarus、E2 GPU 整數 ACS 位元相等、E3 SAIF annotation ≥99%。
M1(6):G1 未編碼 BPSK、G2a/G2b 編碼增益、G3 量化損失、G4a/G4b 硬判決損失。
M2(3):C2′、M2 全網格交叉、G6 負向(不安全字寬 BER floor)。
M3(5):三前端一致、G5=C2 位元相等、G6 正向(安全格點不誤觸)、G6 負向 4/4、G7 4-state 交叉。
M4(3):Tier B C2 浸泡、stimulus SHA-256 對帳、G6 浸泡不誤觸。
M5(6):annotation、功耗 vs frame 數、功耗 vs SNR、F1、F2、F3。

`[各 gate 的量測值/目標/容忍完整表格待由 data/gates.csv 生成插入]`
