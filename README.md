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
make env      # M0：工具鏈驗收
make gates    # 所有已上線的 known-answer 閘門 -> data/gates.csv
make sweep    # GPU 設計空間掃描 (Q, clip, W, D) x SNR
make ber      # Tier B 浸泡：解碼位元 XOR，零容忍
make ppa      # 合成 -> gate-level sim -> SAIF -> OpenSTA 分區塊功耗 vs SNR
make report   # check_paper_numbers.py，必須輸出 mismatches: 0
```

報告裡的每個數字都必須存在於 `data/results.csv` 或 `data/gates.csv`，
且可由 `scripts/` 底下的 script 重生。手貼的數字不接受（CLAUDE.md §5.4）。

## 目前進度

| 里程碑 | 狀態 |
|---|---|
| M0 環境建置與工具鏈驗證 | **完成**（E1/E2/E3 全綠，tag `m0-env`） |
| M1 L2 定點 golden model + K=7 浮點參考 | **完成**（G1/G2a/G2b/G3/G4a/G4b 全綠，tag `m1-golden`） |
| M2 GPU 掃描 | **完成**（C2′ 零 mismatch，280 點全網格，4 組 winner，tag `m2-sweep`） |
| M3 RTL + Tier A | **完成**（C2 22,532 stages 零 mismatch，G6 負向 4/4，G7 通過，tag `m3-rtl`） |
| M4 Tier B + G6 浸泡 | **完成**（2.47 億 stage 浸泡零 mismatch，tag `m4-tierb`） |
| M5 PPA + 能量模型 | 未開始 |
| M6 報告 | 未開始 |

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
