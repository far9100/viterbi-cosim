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
| M0 環境建置與工具鏈驗證 | **完成**（E1/E2/E3 全綠） |
| M1 L2 定點 golden model + K=7 浮點參考 | 未開始 |
| M2 GPU 掃描 | 未開始 |
| M3 RTL + Tier A | 未開始 |
| M4 Tier B + G6 浸泡 | 未開始 |
| M5 PPA + 能量模型 | 未開始 |
| M6 報告 | 未開始 |
