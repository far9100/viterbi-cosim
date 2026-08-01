# M14 實作筆記：B2 的 RTL 設計推導（**不是凍結文件**）

本檔記錄 B2 的 RTL 在動手寫之前推導出來的設計結論。它**不是**凍結文件——
判準與事前預測在 `docs/memory_traceback_baseline.md`，那一份不可修改；
本檔是工程筆記，可以改。

寫下來的理由：這些結論是實作前分析出來的，其中幾條推翻了凍結文件裡
「B2 = 換一個 traceback 模組」的隱含假設。下一次開工的人不必重新推一遍。

## 1. 批次排程（已由 golden 實測確認）

批次觸發於 `t_end = 2D-1, 3D-1, ..., NINFO-1`，每次回走 2D 步，
丟掉最新的 D 個、輸出最舊的 D 個（對應 stage `t_end-2D+1 .. t_end-D`）。

實測涵蓋範圍（`golden/traceback.py` 的 `mode='batch'`，NINFO 是 D 的倍數）：

| D | NINFO | T | 批次數 | 最後 t_end | 批次涵蓋 | 未涵蓋（tail） |
|---|---|---|---|---|---|---|
| 32 | 256 | 262 | 7 | 255 | 0..223 | 224..261（38 個） |
| 32 | 1024 | 1030 | 31 | 1023 | 0..991 | 992..1029（38 個） |
| 64 | 256 | 262 | 3 | 255 | 0..191 | 192..261（70 個） |
| 64 | 1024 | 1030 | 15 | 959 之後 | 0..959 | 960..1029（70 個） |

**tail 長度恆為 D + m = D + 6**，因為最後一個 `t_end` 固定落在 `NINFO-1 = T-m-1`。
這個規律只在 `NINFO % D == 0` 時成立——本專案的 (256, 1024) × (32, 64) 全部滿足，
但若將來加入不整除的組態，tail 長度要重推。

tail 由**終止狀態回溯**解出（從 `s_T = 0` 往回走），與 register exchange 的
flush 同一個做法，只是長度從 D-1 變成 D+m。

## 2. 一步回溯必須與 golden 逐位元相同

```
golden/traceback.py::_pred    s_next = (s >> 1) | (surv[s] << (m-1))
SystemVerilog                 pred(s, sv) = {sv[s], s[VM-1:1]}
```

輸出位元 `out[k] = s & 1` 取在 pred **之前**。這個順序寫錯不會有任何錯誤訊息，
只會讓解碼位元整體偏移一位——`docs/trellis_convention.md` 對 survivor 極性
也是同一類的坑。

## 3. 時序：B2 不是 drop-in（實作前才發現的）

回溯引擎每個 stage 走 **2 步**（一批 2D 步剛好佔滿 D 個 stage）。
收集完的一批在**接下來的 D 個 stage** 逐一吐出，所以：

* 第一個輸出位元（`dec[0]`）要到 `t_done = 3D-1` 才出得來；
  register exchange 是 `D-1`。
* `rtl_lowpower/ctrl.sv:59` 的 `out_valid = (stage_done && (t_done >= D-1)) || flush_en`
  把輸出時序**寫死在深度 D 上**，`S_FLUSH` 的長度也是 `D-1`。

⇒ **B2 需要 `ctrl.sv` 一個可參數化的 `OUT_LAT`（B0/B1 為 `D-1`，B2 為 `3D-1`）
與更長的 flush（`D+m`）。** 兩份凍結文件都把 B2 寫成模組層的替換，那是低估。

工作量因此是「加一個模組 **+ 改狀態機 + 加輸出緩衝 + 重驗控制路徑**」，
而控制路徑的四條測試（gate `M3-1`）是 M12 才補上的，剛好可以直接複用。

## 4. 輸出緩衝必須 ping-pong

第 N 批的**發送**（D 個 stage）與第 N+1 批的**收集**（D 個 stage）在時間上完全重疊。
共用一個緩衝區會讓還沒吐完的位元被下一批蓋掉。

發送順序是**收集順序的反向**（LIFO）：`out[2D-1]` 最後被算出來、卻要最先吐出去
（它對應最舊的 stage `t_end-2D+1`）。所以
收集用 `buf <= {buf[D-2:0], bit}`（左移進 LSB），
發送用 `dec_bit = buf[0]` 後 `buf <= {1'b0, buf[D-1:1]}`（右移）。

## 5. 一個第一版寫錯、值得記下來的地方

引擎每拍走兩步，而「這一批的第 k 步要不要收進緩衝區」的條件是 `k >= D`。
兩步的 `keep` 條件不同（`step >= D` 與 `step+1 >= D`），
在 `step == D-1` 那一拍會出現**只收第二步**的情形。

第一版把兩個 keep 寫成兩個獨立的 `if`，各自對同一個緩衝區賦值 ——
在 always_ff 裡那是後者覆蓋前者，第一步的位元被吃掉。
正確寫法是把三種情形（只收第一步 / 只收第二步 / 兩步都收）合併成單一賦值。

## 6. 建議的實作與驗證順序

1. `rtl_lowpower/traceback_mem.sv`（本檔 §1–§5）。
2. `rtl_lowpower/ctrl.sv` 加 `OUT_LAT` 與 `FLUSH_LEN` 參數；B0/B1 的預設值
   必須讓合成結果**逐位元組不變**（比照 M12 對 `bm_r` 的同一性 gate）。
3. `rtl_lowpower/viterbi_top.sv` 加 `TB_MODE`（0 = register exchange，
   預設；1 = memory），用 `generate` 選擇。
4. `make lint` —— 兩個目錄 × 三個前端。
5. Tier A：新增 `MODE=c2b2`，對 `golden` 的 `mode='batch'` 比對
   `bm`/`pm`/`survivor`/解碼位元。**這一步會抓到所有指標算術的錯**。
6. 合成 → `ppa/verify_cg.py` 加 `_b2_rtlv` 變體的閘級 C2。
7. **才准**量功耗（`docs/memory_traceback_baseline.md` §6.2）。
8. `scripts/m14_gate.py` 依凍結文件 §4/§5 裁決，P4/P5 兩讀都要記錄。

## 7. 目前的狀態

* 已完成：凍結文件、`golden` 的 `mode='batch'`、10 條交叉檢查測試
  （C-B1 實測最大不一致率 **0.0166%**，門檻 1%）。
* 未完成：上面 §6 的第 1 步起全部。
* 第一版 RTL 草稿因為 §5 的錯誤與 tail 未處理而**未提交**——
  未經驗證的 RTL 不進樹，那正是本專案的紀律。
