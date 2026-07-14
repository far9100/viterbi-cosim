# CHANGELOG

## 2026-07-14（M1）

- `2026-07-14-08` add — 三份凍結文件（`trellis_convention` / `traceback_convention` / `wordlength_bound`）。順序是先驗證再記錄：`verify_trellis.py` 實測 (133,171) 的 d_free = 10、butterfly 結構、以及讓 ACS 只需一個 BM 輸入的兩條互補性。其中一條的成立條件是「每個生成多項式為**奇數**（LSB = 1）」，不是計畫書誤植的「MSB tap = 1」——後者是另一條性質的條件，兩條都成立但理由不同。
- `2026-07-14-09` add — L1 浮點參考（K=7 新寫）與 L2 定點 golden model（`pm_mod` mod-2^W 與 `pm_ref` 無界雙軌）。16 個測試全綠，含四個由強到弱的 oracle：暴力 ML 枚舉、既有模擬器經 mutation testing（90.4%）的 K=3 Viterbi、d_free、定點 vs 浮點。
- `2026-07-14-10` debug — 硬判決 branch metric 恆為 0 或 1、永遠到不了 2：numpy 對兩個 bool 陣列做 `+` 是**邏輯 OR** 而非整數相加，解碼器因此分不出「錯一個位元」與「錯兩個位元」，等於不是 ML。自寫的暴力 ML 測試 10/10 通過（短 frame 蓋不到），是 K=3 oracle 在真實 frame 長度下抓到的（path metric 35 vs 28）。
- `2026-07-14-11` debug — BER 的亂數串流用 `hash(str(cfg))` 當 key，但 Python 對字串的 hash 每個 process 隨機加鹽，同一組態在不同 worker、不同次執行拿到不同 seed，結果不可重現（CLAUDE.md §5.3）。改用 sha256，並加了跨 process 的重現性測試。
- `2026-07-14-12` test — M1 閘門全綠（99 個量測點）。G1 未編碼 BPSK @1e-5 = **9.571 dB**（容差 9.588 ±0.1）；G2b 編碼增益 = **5.434 dB**（區間 [5.0, 5.6]），與 `docs/falsification.md` 事前登記的 5.39 dB 相符，且證實規格書 v1 的 5.0±0.3 確實會紅燈；G3 3-bit 量化損失 = **0.225 dB**（最佳 clip 2.5σ，容差 0.20 ±0.15）。
- `2026-07-14-13` audit — G4 的容差被證明不可能達成：硬判決 union bound（定理，獨立於本專案的量測）給出 **2.355 dB**，本身就落在規格 [1.7, 2.3] 之外。改為兩段式 G4a/G4b，**明確標示為事後修正**（強度弱於 G2 的事前修正）。實測損失 **2.413 dB**。
- `2026-07-14-14` debug — G2a/G4a 的判準本身寫錯兩處：(1) **截斷過的 union bound 不是上界**，`d_max=22` 丟掉的尾巴讓硬判決的界低了 0.3%，改用 d_max=30（≥26 後收斂）；(2) 拿有雜訊的估計值對確定的界做零容忍比較在統計上不成立——界很緊時（實測 G2a 最大 實測/界 = 0.981、G4a = 1.034）正確的解碼器也會有約一半機率因雜訊「超出」。判準改為「95% CI 的下緣不得超出界」。
- `2026-07-14-15` test — D 軸驗證 traceback 慣例：D=24（低於 5K=35）損失 **+0.209 dB**，D=32/48/64 全部落在量測雜訊內。C1 網格在 Q≥4 撞到雜訊地板（**±0.076 dB**，由「量化不可能贏過未量化」的負值直接量得）；Q=3 的損失遠高於地板可信，Q≥4 需 M2 的 GPU 掃描才分辨得出來。如實記錄。
- `2026-07-14-16` add — 凍結 46 個 C2 測試向量（輸入逐位元組 + 期望輸出的 SHA-256）。G6 負向測試 4/4 於 **stage 0** 觸發，實測 PM spread（187 / 401 / 844 / 857）在每一格都低於最壞界卻高於 2^(W−1)——證實界是充分非必要條件，且初始化才是綁住字寬的那一項。
- `2026-07-14-17` debug — 量測的平行度由 14 降到 8：traceback 對 26 MB 的 survivor 陣列做隨機 gather，14 個 worker 讓記憶體頻寬先飽和，總吞吐反而比 8 個低（1578 vs 1686 kb/s），且單 job 慢 1.6 倍（189s vs 117s）。與規格書 §4「不要依賴 Verilator --threads」是同一個道理，只是發生在 numpy 這一側。

## 2026-07-14（M0）

- `2026-07-14-01` audit — 規格書 v1 審查：5 個前提經實測不成立（K=7 浮點參考不存在、RISC-V 的 VCD/SAIF→OpenSTA 功耗流程從未建置、從未用過 OpenLane、Verilator/cocotb/torch 皆未安裝、sky130 cell models 不在 ORFS image 內），6 個技術錯誤（branch metric 取最大/最小自相矛盾、G6 字寬界漏掉初始化、G2 期望值偏低 0.3–0.4 dB、SAIF 不可省略、Icarus 不支援 bind/concurrent SVA、掃描規模漏掉 clip 軸），3 個會改變結果的模糊處。
- `2026-07-14-02` plan — 四項決策定案：執行環境落在 WSL2 原生 FS；traceback 採 sliding-window + best-state 且解碼位元納入 C2 比對集；G2 改為兩段式（G2a union bound 零容忍 + G2b 增益區間 [5.0, 5.6] dB）；能量模型採「規格模型 + 補齊常數 + WSN 標準電路功耗」雙曲線。
- `2026-07-14-03` add — `docs/energy_model.md` 與 `docs/falsification.md` 於任何量測開跑前提交。事前估計 d\* ∈ [13.7 m（模型 A 室內）, 5.4 km（模型 B 自由空間）]，故規格書 §0 的「d\* < 1 m 即證偽」實質不可觸發；追加兩條可證偽的預先登記：Q 3→6 使 d\* 移動 < 5% 則「字寬移動臨界距離」的貢獻宣稱失敗；模型 A 預測 +1.6%～+2.8%、模型 B 預測 −0.5%～−0.9%（**符號相反**）。
- `2026-07-14-04` add — M0 環境建置。Verilator 5.051 + Icarus 14.0 由 oss-cad-suite 安裝（免 root，取代原計畫的「apt + 源碼編譯 Verilator」）；torch 2.11.0+cu128 在 sm_120 上通過整數 ACS 與 numpy 的逐位元組比對，含 123 個平手樣本（證明 tie-break 語意確有被測到）。
- `2026-07-14-05` add — gate-level 功耗流程從零建置（RISC-V 專案零複用）：Yosys 0.64（階層式，不 flatten）→ Icarus + vendored sky130 cell models（commit `ac7fb61f`）→ VCD →`ppa/vcd2saif.py`（FIFO 串流，VCD 不落地）→ OpenSTA `read_saif -scope`。以 8-bit counter 驗收，**activity annotation coverage 100%（117/117 pins，零 unannotated）**。
- `2026-07-14-06` debug — 煙霧測試抓到 `vcd2saif.py` 的 timescale bug：iverilog 把 `$timescale` 寫成跨行，單行 regex 比對失敗後靜默退回預設值 `1 ns`，但實際單位是 `1 ps`，導致 SAIF 的 DURATION 差 1000 倍、OpenSTA 算出的翻轉密度跟著錯 1000 倍。修正後組合邏輯的 switching power 由 1.556e-09 W 變為 1.556e-06 W（正好 1000×），且功耗數字在修正前**看起來完全正常、沒有任何錯誤訊息**。
- `2026-07-14-07` test — M0 驗收閘門 E1/E2/E3 全綠，寫入 `data/gates.csv`。counter 的功耗分佈為 Sequential 88.5% / Combinational 11.5%，與「survivor 記憶體支配 Viterbi 功耗、總功耗對 SNR 可能近乎平坦」的預測方向一致（風險 R1）。
