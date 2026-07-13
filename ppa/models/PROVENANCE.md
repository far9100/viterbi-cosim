# sky130_fd_sc_hd cell models —— 來源與雜湊

Gate-level 模擬需要 cell 的行為模型。ORFS Docker image **不含**這些檔案（它只出貨
lib/lef/gds，從不模擬 gate），因此必須另外取回並入庫。這是本專案唯一一批 vendored 的
第三方原始碼。

| 項目 | 值 |
|---|---|
| 來源 | https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd |
| git commit | `ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1` |
| 取回日期 (UTC) | 2026-07-13 |
| .v 檔案數 | 2310 |
| 大小 | 9.8M |
| 內容雜湊 | `5a6b0ce284f029db2b75a2ab506fa4c8d5d57ed09cdf71a032400e8e0ee6a619` |

內容雜湊可重算：

```bash
cd ppa/models/sky130_fd_sc_hd && find . -type f -name '*.v' | sort | xargs sha256sum | sha256sum
```

## 目錄結構（不可攤平）

    ppa/models/sky130_fd_sc_hd/
    ├── cells/<cellname>/sky130_fd_sc_hd__<cellname>_<drive>.v   <- netlist 實例化的就是這些
    │                    sky130_fd_sc_hd__<cellname>.v            <- dispatcher
    │                    sky130_fd_sc_hd__<cellname>.functional.v
    └── models/udp_*/    sky130_fd_sc_hd__udp_*.v                 <- 序向 cell 的 UDP primitive

序向 cell 的 functional model 用**相對路徑** include UDP primitive
（`../../models/udp_dff_p/...`），所以 cells/ 與 models/ 的相對位置**必須保留**。
攤平會讓 iverilog 在前處理階段就失敗。

## 編譯時的 define

| define | 設定 | 理由 |
|---|---|---|
| `USE_POWER_PINS` | **不定義** | Yosys 產出的 netlist 沒有 power pin；定義了會 port 數不符。 |
| `FUNCTIONAL` | **定義** | 選 `.functional.v`。不定義會選 `.behavioral.v`，那裡的 `specify` block 需要 SDF 反標註才有意義。 |
| `UNIT_DELAY` | `#1` | 給每個 cell 一個時間單位的延遲，讓結構性 hazard（glitch）能傳播。零延遲模擬完全沒有 glitch，會系統性低估動態功耗。 |

**已知偏差**：UNIT_DELAY 不是真實 SDF 標註的延遲，glitch 行為只是近似。方向不明，
已記錄於 `docs/energy_model.md` §6。
