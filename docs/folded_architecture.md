# 凍結文件：折疊架構（PAR = 32 / 8 / 1）的定義、判準與事前預測

**本文件在任何折疊架構的量測開跑之前提交。** commit 時間戳可由 git 驗證，
且 `scripts/check_paper_numbers.py` §4 的預先登記檢查會把「本文件的 commit 早於
`data/power_folded.json`」列為硬性條件（最小間隔 1 小時，見 `PREREG_MIN_GAP_H`）。

## 0. 這一項的來歷：一個被裁定跳過、現在補做的交付物

規格書 §7 原本要求 PPA 表涵蓋**三種平行度**（PAR = 32 / 8 / 1）。
使用者當時裁定跳過，於是 PPA 表如實標註「僅 full-parallel」，
並在 `docs/report.md` §5-5、`docs/thesis.md` §8.2、`README.md`、
規格書 `:524` 四處記為「未做」。

2026-08-01 經作者書面確認後補做。**那四處的「未做」不得刪除**，
處理規則見 §4。

## 1. PAR 的精確定義

`PAR` = 每個 trellis stage 同時計算的 butterfly 數。K=7 有 32 個 butterfly，
所以一個 stage 需要 `32 / PAR` 個 cycle：

| PAR | butterfly 實例 | cycles / stage | PM 讀寫 |
|---|---|---|---|
| 32 | 32（現況） | 1 | 全部 64 個狀態同時更新 |
| 8 | 8 | 4 | 每 cycle 更新 16 個狀態 |
| 1 | 1 | 32 | 每 cycle 更新 2 個狀態 |

`stage_done` 仍然是**每個 stage 一個脈衝**（在該 stage 的最後一個 cycle）。
這一點是 C2 能不能沿用的關鍵，見 §2。

折疊只改 ACS 的排程，**不改演算法**：`bm`、`pm`、`survivor` 在每個 stage 邊界上的值
必須與 PAR=32 逐位元相同。因此 C2 的比對標的完全不變，golden model 一行都不用改。

## 2. 「TB 可以零修改沿用」是一條**預測**，不是前提

`tb/cocotb/test_viterbi.py:14-19` 寫著：

> 用脈衝觸發的另一個好處：將來的折疊架構（PAR=8 / PAR=1，一個 stage 要好幾個 cycle）
> 可以完全沿用這套 testbench，**零新程式碼**。

規格書 §2.1 也以此為據。**但那從來沒有被驗證過**，而且介面層有一個已知的障礙：
`rtl/ctrl.sv:57` 的 `stage_en = (st == S_RUN) && in_valid`，
以及介面上**沒有 `in_ready`** —— 也就是說目前的設計假設「每個 cycle 吃一個 stage 的輸入」。
PAR=8 時一個 stage 要 4 個 cycle，輸入端必須知道什麼時候該保持、什麼時候該前進。

所以把它降級為可證偽的事前預測：

* **P-F1（比對邏輯零修改）**：`test_viterbi.py` 中**以 `stage_done` 觸發的比對段落**
  完全不需要修改。這是那句宣稱真正站得住的部分。
* **P-F2（激勵驅動端必須修改）**：Tier A、`tb/gl/tb_viterbi_file.sv`、
  `tb/cpp/sim_main.cpp` 三個 driver **都必須改**——不是新增 `in_ready` 交握，
  就是由 TB 自己把 `r0`/`r1` 保持 `32/PAR` 個 cycle。
  **預測：三個都要改。** 若其中任何一個真的零修改就能跑，這條被推翻。
* 若 **P-F1 被推翻**（比對邏輯也要改），那是規格書 §2.1 與 `test_viterbi.py:14-19`
  **兩處宣稱同時被推翻**，必須如實記載，並回頭修正那兩處的文字。

## 3. 事前預測（量測前寫死，不得事後修改）

* **P-F3（面積不與 1/PAR 成比例）**：`u_acs` 的面積會隨 PAR 下降，
  但**總面積不會**。理由：PM register file（64×W）與 traceback（64×D）
  完全不隨 PAR 縮，而它們在 PAR=32 時就已經是面積大宗
  （M5 實測 min-PM 佔 11.8–19.7%、traceback 佔大宗）。
  **定量預測**：Q4 W10 D64 從 PAR=32 到 PAR=1，
  **總面積降幅落在 15%–40%**（不是 1/32）。
  低於 15% 表示 ACS 本來就不重要；高於 40% 表示我對面積組成的理解錯了。
* **P-F4（Fmax 會上升）**：折疊讓 `stage_en` 的扇出下降
  （PAR=1 時每個 cycle 只更新 2 個狀態），而 M5 實測 PAR=32 的關鍵路徑
  正是那條扇出 8683 個 sink、18.10 pF 的 enable 網。
  **預測：PAR=1 的 `repair_design` 後 Fmax 高於 PAR=32 的 150.2 MHz。**
* **P-F5（每位元能量會上升）**：折疊省的是面積不是能量——
  同樣的 trellis 運算量攤在更多 cycle 上，而漏電與時脈樹的時間變長。
  **預測：PAR=1 的 E_dec（pJ/bit）比 PAR=32 高 10%–100%。**
  這一條與 P-F3 方向相反，是刻意的：折疊若同時省面積又省能量，
  那 M5「full-parallel 是能量最佳」的隱含假設就錯了，那會是一個更大的結果。

## 4. 「未做」的四處揭露怎麼處理（規則寫死）

`docs/report.md` §5-5、`docs/thesis.md` §8.2、`README.md`、
`docs/fec_viterbi_cosim_spec.md:524` 目前都寫著折疊架構「未做」。

**一律改寫為**：

> 原裁定跳過（2026-07-17），2026-08-01 經作者書面確認後補做，結果見 §X。

**不得刪除、不得改寫成好像從來沒有跳過過。** 一個交付物被跳過再補做，
「曾經被跳過」本身就是專案史的一部分；把它抹掉會讓讀者無法判斷
哪些東西是原計畫、哪些是後來補的。

## 5. 架構落地方式：先試參數化，過不了就退回副本

**優先做法：把 `rtl/` 參數化（`parameter int PAR = 32`），不開 `rtl_folded/` 副本。**

理由：`rtl_lowpower/` 的存在已經製造了兩個實際問題——它一度不被 lint、
不進 Tier A（M12 才補上），而且讓 RTL 檔案清單在 5 處重複（M12-1 才收斂）。
再開第三份必然重演。

**但這動到 `rtl/`，是整個補做計畫裡風險最高的改動**，所以設兩道硬 gate：

* **同一性 gate**：`PAR=32` 合成出來的 netlist，其 cell 組成與總面積
  必須與現行的 `net_Q*.v` **逐項相同**。
* **回歸 gate**：Tier A 的 C2 22,532 個 stage 不變、G6 負向 4/4、G7 綠、
  控制路徑 4/4（gate `M3-1`）、Tier B 抽驗一組零 mismatch。

**任一不過就退回 `rtl_folded/` 副本**，並把「參數化會擾動 PAR=32」
如實記錄為一個發現——那本身是關於這份 RTL 可維護性的資訊。

`ctrl.sv` 需要新增 `in_ready`（PAR=32 時恆為 1，介面向後相容），
`tb/gl/tb_viterbi_file.sv` 與 `tb/cpp/sim_main.cpp` 跟著加交握（見 P-F2）。

## 6. 不因為折疊而改變的事

1. **annotation coverage ≥ 99% 不放寬**（規格書 §7）。
2. **先過 C2 才准量功耗**：合成 → RTL 層 C2（Tier A，三種 PAR 都要）
   → 閘級 C2 → 才量功耗。
3. **PAR=32 的既有數字原樣保留，不重算**——同一性 gate 就是為了保證這一點。
4. `golden/` 完全不動。折疊只改 ACS 的排程，不改演算法。

## 7. 產物清單

| 產物 | 內容 |
|---|---|
| `data/power_folded.json` | PAR ∈ {32, 8, 1} 的閘級功耗點 |
| `data/results_m15_ppa.csv` | 三種 PAR 的面積、Fmax、E_dec（規格書 §7 要的那張表） |
| `data/results_m15_blocks.csv` | 分區塊面積與功耗，供 P-F3 裁決 |
| `figures/fig_m15_par.png` | 面積 / Fmax / E_dec 對 PAR 的三聯圖 |
| SAIF | 依 M9 的裁決一併歸檔，寫入 `MANIFEST_m15.sha256` |

---

凍結於 2026-08-01。本文件之後的任何修改只能以檔尾追加勘誤帶的方式進行
（`docs/errata.md` 的機制），本體逐位元組不可變，由 `check_paper_numbers.py` §6 檢查。
