# CHANGELOG

## 2026-07-14

- `2026-07-14-01` audit — 規格書 v1 審查：5 個前提經實測不成立（K=7 浮點參考不存在、RISC-V 的 VCD/SAIF→OpenSTA 功耗流程從未建置、從未用過 OpenLane、Verilator/cocotb/torch 皆未安裝、sky130 cell models 不在 ORFS image 內），6 個技術錯誤（branch metric 取最大/最小自相矛盾、G6 字寬界漏掉初始化、G2 期望值偏低 0.3–0.4 dB、SAIF 不可省略、Icarus 不支援 bind/concurrent SVA、掃描規模漏掉 clip 軸），3 個會改變結果的模糊處。
- `2026-07-14-02` plan — 四項決策定案：執行環境落在 WSL2 原生 FS；traceback 採 sliding-window + best-state 且解碼位元納入 C2 比對集；G2 改為兩段式（G2a union bound 零容忍 + G2b 增益區間 [5.0, 5.6] dB）；能量模型採「規格模型 + 補齊常數 + WSN 標準電路功耗」雙曲線。
- `2026-07-14-03` add — `docs/energy_model.md` 與 `docs/falsification.md` 於任何量測開跑前提交。事前估計 d\* ∈ [13.7 m（模型 A 室內）, 5.4 km（模型 B 自由空間）]，故規格書 §0 的「d\* < 1 m 即證偽」實質不可觸發；追加兩條可證偽的預先登記：Q 3→6 使 d\* 移動 < 5% 則「字寬移動臨界距離」的貢獻宣稱失敗；模型 A 預測 +1.6%～+2.8%、模型 B 預測 −0.5%～−0.9%（**符號相反**）。
- `2026-07-14-04` add — M0 環境建置。Verilator 5.051 + Icarus 14.0 由 oss-cad-suite 安裝（免 root，取代原計畫的「apt + 源碼編譯 Verilator」）；torch 2.11.0+cu128 在 sm_120 上通過整數 ACS 與 numpy 的逐位元組比對，含 123 個平手樣本（證明 tie-break 語意確有被測到）。
- `2026-07-14-05` add — gate-level 功耗流程從零建置（RISC-V 專案零複用）：Yosys 0.64（階層式，不 flatten）→ Icarus + vendored sky130 cell models（commit `ac7fb61f`）→ VCD →`ppa/vcd2saif.py`（FIFO 串流，VCD 不落地）→ OpenSTA `read_saif -scope`。以 8-bit counter 驗收，**activity annotation coverage 100%（117/117 pins，零 unannotated）**。
- `2026-07-14-06` debug — 煙霧測試抓到 `vcd2saif.py` 的 timescale bug：iverilog 把 `$timescale` 寫成跨行，單行 regex 比對失敗後靜默退回預設值 `1 ns`，但實際單位是 `1 ps`，導致 SAIF 的 DURATION 差 1000 倍、OpenSTA 算出的翻轉密度跟著錯 1000 倍。修正後組合邏輯的 switching power 由 1.556e-09 W 變為 1.556e-06 W（正好 1000×），且功耗數字在修正前**看起來完全正常、沒有任何錯誤訊息**。
- `2026-07-14-07` test — M0 驗收閘門 E1/E2/E3 全綠，寫入 `data/gates.csv`。counter 的功耗分佈為 Sequential 88.5% / Combinational 11.5%，與「survivor 記憶體支配 Viterbi 功耗、總功耗對 SNR 可能近乎平坦」的預測方向一致（風險 R1）。
