# `rtl_lowpower/` —— 可 clock gate 的 RTL 變體（M9 / B0′、B1′）

本目錄是 `rtl/` 的變體，**只改一件事**：把同步 reset 寫進時脈致能條件。
`rtl/` 是 M3 驗證過、M5 量測過、報告數字所依據的版本，**不動**。

## 為什麼需要這個變體

Yosys 的 `clockgate` pass 從 FF 的 CE 腳推導 enable，而**同步 reset 不在 CE 裡**
（Yosys 把它折進 D 路徑，netlist 端是 `dfxtp` + reset mux）。於是：

```
rst = 1、stage_en = 0  ⇒  ICG 把時脈關掉  ⇒  reset 永遠進不去  ⇒  設計卡在 X
```

**症狀極隱蔽**：`tb/gl/tb_viterbi_file.sv` 只在 `out_valid === 1'b1` 時檢查 X/Z，
而 `out_valid` 自己就是 X ⇒ TB 回報的是「收到 0 個輸出」，**不是「X 錯誤」**。
一個功能完全壞掉的 netlist 照樣會產生 SAIF、照樣會被 OpenSTA 算出漂亮的功耗數字。
**是 C2 擋下來的**（`ppa/verify_cg.py`，`docs/lowpower_baseline.md` §4.1 的硬性順序）。

## 改法（三個檔案，語意等價）

`acs_array.sv`（`pm`、`surv_r`）、`traceback.sv`（`re`）、`viterbi_top.sv`（`bm_r`）：

```systemverilog
// rtl/（原版）                          // rtl_lowpower/（可 gate）
if (rst)        x <= RESET_VAL;          if (rst || en) x <= rst ? RESET_VAL : d;
else if (en)    x <= d;
```

reset 在兩種寫法下都有優先權，行為完全相同；差別只在 Yosys 看得到的 CE 是
`en` 還是 `rst | en`。**`ctrl.sv` 刻意不改** —— 見下。

## `ctrl.sv` 為什麼不改，改用 `-min_net_size`

控制 FSM 的 enable 由它自己的狀態導出，改寫會牽動 FSM 的可讀性，而它只有數十個 flop，
gate 了也省不到功耗。改以 `ppa/synth.py` 的 `CG_MIN_NET = 64` 把小群組排除在 gating 之外：
只 gate traceback（64×D）、PM（64×W）、`surv_r`（64）三組真正大的暫存器庫。

## 三態的實測（Q3 W8 D32，C2 全部通過）

| 態 | RTL | clock gating | 面積 (µm²) | 相對 B0 |
|---|---|---|---|---|
| **B0** | `rtl/` | 無 | 157,527 | — |
| **B0′** | 本目錄 | 無 | 163,888 | **+4.04%** |
| **B1′** | 本目錄 | 有 | 140,166 | **−11.02%** |

**RTL 改寫本身要付 +4.04% 的面積**（Yosys/abc 對 `rst ? c : d` 的映射與原版不同），
這是必須控制的**混淆因子**——沒有 B0′ 這一欄，就無法把 −11.02% 全歸給 clock gating。
純 clock gating 的效果是 B0′ → B1′ 的 **−14.47%**。

`rtl/` 的 B0 數字因此完全不受本目錄影響，報告已發表的 PPA 與 d\* 不需重算。
