# 凍結文件：B2（記憶體式回溯）的定義、判準與事前預測

**本文件在任何 B2 量測開跑之前提交。** commit 時間戳可由 git 驗證，
且 `scripts/check_paper_numbers.py` §4 的預先登記檢查會把「本文件的 commit 早於
`data/power_b2.json`」列為硬性條件（最小間隔 1 小時，見 `PREREG_MIN_GAP_H`）。

## 0. 為什麼有這份文件

`docs/lowpower_baseline.md` §2 定義了三個狀態 B0 / B1 / B2 並登記了五條預測，
但 **B2 從未建置**——`scripts/m9_gate.py` 至今仍印「P4/P5（memory traceback）-> 尚未執行」。
那是本專案唯一一條「已凍結預先登記卻沒有執行」的預測，也是 M9 那份文件
自己指出的樞紐：

> 真正的樞紐是 B2（register exchange 每 stage 改寫 64×D 個 flop，
> 記憶體式回溯每 stage 只寫 64 bits，那是數量級差別）。

M9 實測 clock gating 讓總功耗掉 42.7%，其中 traceback 掉 58.5%、佔比從 66.75%
降到 48.36%。**但 traceback 仍然是最大的單一區塊。** B2 要問的是：換掉回溯**架構**
（而不只是加 clock gating）之後，那個分母還剩多少。

本文件補上 `lowpower_baseline.md` 沒有寫的部分：B2 的精確定義、它為什麼過不了
現行的 C2、以及功耗要拿什麼跟什麼比。

## 1. B2 的精確定義

**batch（one-pointer）回溯，記憶體深度 2D。** 與現行的 register exchange 對照：

| | register exchange（B0/B1） | batch 回溯（B2） |
|---|---|---|
| 每個 stage 的寫入量 | 64 × D 個 flop 全部改寫 | 64 bits（只寫當拍的 survivor） |
| 記憶體 | 64 × D | 64 × 2D |
| 輸出時機 | 每個 stage 出一個位元 | 每 D 個 stage 出 D 個位元（成批） |
| 有效回溯深度 | **恰好 D** | **∈ [D, 2D]** |

pseudo-code（格式比照 `docs/traceback_convention.md` §2）：

```python
# surv_mem[t % (2D)][s] = stage t 上狀態 s 的 survivor bit
# 每 D 個 stage 觸發一次批次回溯
if (t + 1) % D == 0 and t + 1 >= 2 * D:
    s = argmin_modulo(pm[t], W)          # 與 register exchange 用同一支 argmin
    out = []
    for k in range(2 * D):               # 回走 2D 步
        b = surv_mem[(t - k) % (2 * D)][s]
        out.append(s & 1)                # 解出的資訊位元（同 trellis 慣例）
        s = (s >> 1) | (b << (VM - 1))   # 前一個狀態
    # out[0] 對應 stage t，out[2D-1] 對應 stage t-2D+1。
    # **丟掉最新的 D 個，輸出最舊的 D 個**（它們的有效深度才 >= D）
    emit(reversed(out[D:2 * D]))         # 對應 dec[t-2D+1 .. t-D]
```

有效深度的區間是**演算法定義的**，不是實作細節：位置 `t-2D+1` 的位元回溯了 2D 步，
位置 `t-D` 的位元回溯了 D 步，中間線性分布。

## 2. 這**不是** SRAM macro

`surv_mem` 以**推論式記憶體**實作（`logic [63:0] mem [0:2*D-1]`），
交給 Yosys 推成 flop 陣列。**SRAM macro 仍在本專案範圍之外**（作者裁定，
`docs/report.md` §5-5 已如實記載）。

**事前承認一件事**：flop 推論的 64×2D 在面積上**會比** register exchange 的
64×D 大，因為記憶體深度加倍。B2 的賣點是**切換活動**（每 stage 寫 64 bits
而不是改寫 64×D 個 flop），不是面積。這句話寫在量測之前，
免得事後拿它當藉口。

## 3. C2 怎麼辦（本文件最關鍵的一節）

`rtl/traceback.sv` 的檔頭已經指出：記憶體式回溯的有效深度 ∈ [D, 2D]，
**過不了現行的 C2**——因為 L2 golden 的 `mode='window'` 是 uniform depth D。

處置分三層，**沒有任何一層是放寬**：

### 3.1 `bm` / `pm` / `survivor`：原樣保留，零容忍

回溯架構**完全不影響**前向遞迴。B2 只改「survivor → 解碼位元」那一段映射。
所以這三項對既有 L2 golden 的逐 stage 比對**一字不改、零容忍**。

### 3.2 解碼位元：對 `golden.traceback(mode='batch')`

golden 端新增第三個模式（現有 `window` / `ml`），實作上面 §1 的 pseudo-code。

**這是擴充 C2，不是削弱 C2。** 理由必須講清楚：有效深度 ∈ [D, 2D] 是
**演算法的定義**，不是 RTL 的實作細節（不像 pipeline 深度或握手時序）。
`docs/traceback_convention.md` 早就為 `window` 與 `ml` 各凍結了一份語意；
`batch` 是第三份同性質的語意。golden 端有對應的凍結語意，是正確的做法，
不違反實作獨立性（CLAUDE.md §5.2）——**違反的做法是讓 golden 去模仿 RTL 的時序**，
而這裡改的是演算法。

### 3.3 交叉檢查：防止兩邊一起錯

3.2 有一個結構性風險：golden 的 `batch` 與 RTL 的 `traceback_mem` 若對同一個
誤解達成共識，C2 照樣零 mismatch。所以另加兩條**與 C2 獨立**的檢查：

* **C-B1**：`batch(D)` 與 `window(D)` 的解碼位元不一致率必須 **< 1%**。
  兩者的有效深度都 ≥ D，在 4 dB 以上不一致的位元應該極少。
  超過 1% 代表 batch 的指標算術錯了（例如丟錯半邊、或回走步數錯）。
* **C-B2**：`batch(D)` 與 `window(D)` 在 1e-5 的 required Eb/N0 差
  必須落在 **±0.076 dB**（C1 的量測雜訊地板，`data/c1_quantization_loss.csv` 估得）之內。
  batch 的有效深度 ≥ D，BER 只會**更好或相同**，不可能顯著更差。

兩條容差**在此寫死**，事後不得放寬。

## 4. 功耗要拿什麼跟什麼比（事前選定）

同一個 D 之下，B1′（uniform D）與 B2（有效深度 ∈ [D, 2D]）的 **BER 不同**，
所以「同 D 比功耗」是被混淆的比較：B2 多花的功耗有一部分買到了更好的 BER。

**頭條比較採「匹配 D」，附表給「匹配 BER」。** 理由：

* 本專案的設計空間軸是 (Q, clip, D)，而 D 是 PPA 的自由度。
  「同一個 D 換掉回溯架構，功耗差多少」是設計者真正會問的問題。
* 「匹配 BER」需要先知道 B2 在哪個 D 上與 B1′ @D=64 等效，
  那本身是量測結果，拿它當頭條會讓比較基準依賴於待測量。

兩者都報，**不得只報好看的那一個**。

## 5. 事前預測（量測前寫死，不得事後修改）

沿用 `docs/lowpower_baseline.md` §2 的 P4 / P5，原文一字不改：

* **P4**：B2 使 traceback 的功耗佔比降到 **20% 以下**。
* **P5**：B2 使總功耗對 SNR 的變動升到 **2–5%**。

**但必須明講**：P4/P5 登記時**沒有預見有效深度會從 D 變成 [D, 2D]**
（`lowpower_baseline.md` 只寫「memory traceback」四個字，沒有定義它）。
因此裁決時**「匹配 D」與「匹配 BER」兩讀都要做、都要記錄**，
不得因為某一讀比較好看就只報那一讀。

本文件另追加三條 B2 專屬的預測：

* **P-B3（面積會上升）**：`u_tb` 的面積比 B1′ 增加 **+60% 以上**
  （記憶體深度 D → 2D，而 register exchange 的每個 flop 還帶一個 2:1 mux，
  所以不是單純的兩倍）。這一條與 P4 方向相反，是刻意的：
  B2 若同時省功耗又省面積，那我對機制的理解就是錯的。
* **P-B4（切換活動會大幅下降）**：`u_tb` 的 switching power 降 **70% 以上**。
  機制：每 stage 的寫入量從 64×D 個 flop 降到 64 bits，是 D 倍的差距（D=32 或 64）。
  這是 B2 唯一的賣點，若降幅小於 70%，機制推理就有問題。
* **P-B5（總功耗會下降，但幅度小於 traceback 的降幅）**：總功耗降 **20%–50%**。
  上界來自 traceback 在 B1′ 只佔 48.36%，下界來自 P-B4 的 70%。
  落在區間外表示有沒被預見的成本（例如批次回溯的組合邏輯）。

## 6. 不因為 B2 而改變的事

1. **annotation coverage ≥ 99% 不放寬**（規格書 §7）。
2. **先過 C2 才准量功耗**（`docs/lowpower_baseline.md` §4.1）——
   順序是：合成 → RTL 層 C2（Tier A）→ 閘級 C2（`ppa/verify_cg.py`）→ 才量功耗。
3. **B0 / B0′ / B1′ 與 M5 的既有數字原樣保留，不重算**
   （`docs/lowpower_baseline.md` §4.3）。
4. `rtl/` 完全不動。B2 只出現在 `rtl_lowpower/`，由 `TB_MODE` 參數選擇。

## 7. 產物清單

| 產物 | 內容 |
|---|---|
| `data/power_b2.json` | B2 的閘級功耗點（與 B1′ 相同的 SNR 與激勵） |
| `data/results_m14_b2.csv` | 三態（B1′ / B2@D / B2@匹配BER）的總功耗、全距、斜率 |
| `data/results_m14_blocks.csv` | 分區塊功耗與佔比（P4 的裁決依據） |
| `data/results_m14_ber.csv` | C-B1 / C-B2 的交叉檢查數字 |
| `figures/fig_m14_b2.png` | 三態的分區塊功耗對照 |
| SAIF | 依 M9 的裁決一併歸檔，寫入 `MANIFEST_m14.sha256` |

---

凍結於 2026-08-01。本文件之後的任何修改只能以檔尾追加 `▼▼▼` 勘誤帶的方式進行
（`docs/errata.md` 的機制），本體逐位元組不可變，由 `check_paper_numbers.py` §6 檢查。
