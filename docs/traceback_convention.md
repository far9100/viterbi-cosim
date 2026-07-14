# Traceback 慣例（凍結）

> **為什麼這份文件非有不可**：C2 只比對 `bm` / `pm` / `survivor`。
> 但 traceback 策略不同，會產生**不同的解碼位元**、不同的 BER，卻**完全通得過** C2。
> 所以解碼位元也被納入 C2 的比對集（規格書 §6 的 G5），而它的語意必須先凍結。
>
> 這不違反獨立性規則：規格書 §2.1 禁止的是 golden model 模仿 RTL 的
> **pipeline / handshaking / 延遲**，不是禁止兩邊共用演算法定義。

## 1. 記號

- stage index `t = 0 .. T-1`，`T = n_info + 6`（terminated frame，6 個 tail bits）
- `s_t` = 處理第 t 個輸入前的狀態；`s_0 = 0`，`s_T = 0`（終止）
- `surv[t][s]` = 在 stage t 為**新狀態** s 記錄的 survivor bit（見 trellis_convention §3）
- 一步回溯：`pred(t, s) = (s >> 1) | (surv[t][s] << 5)`，把 `s_{t+1}` 映回 `s_t`
- 進入狀態 s 的輸入位元 = `s & 1`

## 2. 主體：uniform depth D 的 sliding window

**每個 stage 從 min-PM 狀態往回追固定 D 步，輸出 1 個位元。**

```python
for t in range(D - 1, T):
    b = argmin_modulo(pm[t + 1])       # 見 wordlength_bound.md §6
    s = b                              # s = s_{t+1}
    for k in range(D - 1):
        s = pred(t - k, s)             # 走 D-1 步 => s = s_{t-D+2}
    dec[t - D + 1] = s & 1             # = u_{t-D+1}
```

涵蓋的輸出索引：`dec[0] .. dec[T-D]`。

**每個位元的有效回溯深度都恰好是 D。** 這是「traceback depth D」的教科書定義，
也是讓 D 軸有意義的唯一寫法——D=24（低於 5K=35）會可觀地變差，D=64 接近最佳。

## 3. 尾端：利用 termination 沖出剩下的 D−1 個位元

```python
s = 0                                  # s_T = 0（終止）
for t in range(T - 1, T - D, -1):      # t = T-1 .. T-D+1
    dec[t] = s & 1
    s = pred(t, s)
```

第一次迭代 `dec[T-1] = 0 & 1 = 0` —— 正是 tail bit，自洽。

尾端這 D−1 個位元是用「從已知終止狀態出發的精確回溯」解出來的，比 sliding window 更好。
真實硬體也是這樣做（frame 結束時 survivor 記憶體裡還留著最後 3D 個 stage）。

## 4. `mode='ml'`：全幀回溯（對照組，不是 C2 標的）

```python
s = 0
for t in range(T - 1, -1, -1):
    dec[t] = s & 1
    s = pred(t, s)
```

用途：`windowed(D) − ML` 的 dB 差是**免費的設計空間結果**——不必動 RTL 就能拿到
「D=24 會壞」的負向資料點，也直接驗證了 D 軸。

## 5. 對 RTL 的約束（M3 要面對的）

本文件定義的是 **uniform depth D**。RTL 必須產生**逐位元相同**的解碼位元。

這排除了教科書上常見的「one-pointer 批次 traceback」（每 D 個 stage 從 argmin 起回走 2D 步、
丟掉最新的 D 個、輸出最舊的 D 個）：那個方案的有效深度落在 **[D, 2D]** 而不是固定 D，
解碼位元會與本文件不同，C2 會噴 mismatch。

能在 1 bit/cycle 下達成 uniform depth D 的自然選擇是 **register exchange**：
64 個狀態各持有一個 D-bit 暫存器，每個 stage 做

```
RE_new[s'] = (RE[pred(s')] << 1) | (s' & 1)
dec        = MSB of RE[best_state]
```

面積 64 × D 個 flop（D=32 → 2048），比 memory traceback 的 64 × 3D = 6144 bits **更小**，
但每個 stage 全部 64 個暫存器都要改寫，**翻轉率高、功耗高**。

這正好是一個有意思的 PPA 對照：

| | 面積 | 每 stage 的寫入 | 需要 traceback FSM |
|---|---|---|---|
| Register exchange | 64 × D flops | 64 × D bits（全改寫） | 否 |
| Memory traceback | 64 × 3D bits | 64 bits（一列） | 是（2 讀/cycle） |

**M3 開工時要定案採哪一種**（或兩種都做，當作 PPA 比較點）。
不論選哪一種，解碼位元都必須與本文件的 uniform-depth-D 語意逐位元相同。

## 6. 輸出延遲

Uniform-depth-D sliding window 的輸出延遲是 **D 個 stage**（register exchange 的自然延遲）。

> 規格書 v1 說 memory traceback 的「輸出延遲 = D」是錯的——批次 memory traceback 是
> **2D–3D**。但那個方案已被本文件排除（見 §5），所以延遲回到 D。
> PPA 表要如實回報實際實作的延遲。
