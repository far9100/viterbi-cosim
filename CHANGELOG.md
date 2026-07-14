# CHANGELOG

## 2026-07-14（M3 + M4）

- `2026-07-14-25` add — RTL：full-parallel（32 個 radix-2 butterfly）+ **register exchange** 的 traceback。依 `docs/traceback_convention.md` 的 uniform-depth-D 語意——教科書的批次 memory traceback 有效深度落在 [D, 2D]，解碼位元會與凍結文件不同。trellis 表由 RTL 自己從八進位多項式推導，**不從 L2 匯入**（共用一份表會讓表格 bug 變成 common-mode，C2 對它完全盲目）。三重前端（Verilator 5.051 / Icarus 14.0 / Yosys 0.64）從第一個 RTL commit 起就跑。
- `2026-07-14-26` test — **G5 = C2：32 組 (Q,W,D) × 86 個 frame × 22,532 個 stage 比對，0 mismatch。** 每個 stage 比對 `bm[4]` / `pm[64]` / `survivor[64]` / **解碼位元**，在 `stage_done` 的脈衝上觸發（不靠數 cycle，這也讓折疊架構將來能零成本沿用同一套 TB）。
- `2026-07-14-27` debug — **C2 抓到的第一個 RTL bug，正是它存在的理由**：`traceback` 被餵了打拍後的 survivor（上一個 stage 的），而 register exchange 的遞迴需要這個 stage 的。症狀極陰險——`bm`/`pm`/`survivor`/`best` **全部完全正確**，只有解碼位元在 frame 頭尾錯掉（256 個位元裡錯 3 個：位置 0、254、255），因為高 SNR 下存活路徑很快收斂。**全零向量完全測不出來**，是全一向量露出來的。只比 bm/pm/survivor 的 C2 會讓這個 bug 完整通過。
- `2026-07-14-28` debug — G6 的 RTL assertion 第一版寫錯：讓影子 PM **跟著 RTL 的決策走**再量 spread。wraparound 一發生，RTL 讓所有狀態都選到錯的分支，影子的 PM 全擠在窄帶裡（Q=4/W=8 是 181–211），**spread 從不變大，assertion 從不響**。改為 `docs/wordlength_bound.md` §5 定義的**決策等價**：影子自己做無界的正確決策，再比對 RTL 的 survivor。
- `2026-07-14-29` test — G6 負向 4/4，全部在 **stage 0** 觸發：Q=4/W=8 spread 181>128、Q=5/W=8 382>128、Q=6/W=8 808>128、Q=6/W=10 776>512。而且這些格點上 **C2 仍然零 mismatch**——RTL 與 golden 錯得一模一樣，這本身就是 C2 有效性最強的佐證。
- `2026-07-14-30` debug — G7（4-state）：cocotb + Icarus 在本機走不通（oss-cad-suite 自帶的 glibc 撐不起 cocotb VPI 要 dlopen 的系統 libpython，GLIBC_2.38；裝系統版 iverilog 需要 root）。改用**檔案驅動**的 SystemVerilog TB，Icarus 這一側完全不碰 Python。10 frames / 2560 bits，C2 零 mismatch 且輸出從未出現 X/Z ⇒ reset 完整。同一支 TB 之後 M5 的 gate-level 模擬也會用到（cocotb 接不上 gate netlist）。
- `2026-07-14-31` add — **Tier B**：C++ harness **沒有 RNG、也沒有量化器**，只重播 L2 匯出的激勵（stimulus.bin + expected.bits + SHA-256 manifest）。規格書 v1 要求的「C++ 的 AWGN 與 L2 位元級一致」做不到（numpy 的 PCG64 + ziggurat 與任何獨立的 C++ RNG 不可能逐位元組相同，除非共用實作——而共用又讓比對變成同義反覆）。這個做法**更強**：只有一份激勵。
- `2026-07-14-32` test — **Tier B 浸泡：12 個點 / 245,760,000 個資訊位元 / 247,200,000 個 trellis stage，解碼位元 XOR 0 mismatch**，SHA-256 12/12 對帳相符。相對 Tier A 擴大 **10,971 倍**。G6 的 assertion 在 2.47 億個 stage 的低 SNR 浸泡中**全程靜默**——而 M3 已證明它在 4 個不安全格點上會於 stage 0 響。Verilator 約 600 kHz（比預估的 2–5 MHz 慢，因為 `--assert` 會把 64-state 的 G6 影子 ACS 也編進去）。
- `2026-07-14-33` audit — 報告必須寫明：**我們不量 RTL 的 BER。** C2 已證明 RTL ≡ golden 逐位元相等，所以兩條 BER 曲線在數學上是同一條；重跑上億位元去「重新量」一條已知的曲線不是驗證，是算術。這是方法學上的強項，不是抄捷徑。

## 2026-07-14（M2）

- `2026-07-14-18` add — GPU golden model（`sweep/viterbi_gpu.py`，torch 整數版，跨 frame batch）與 **C2′ 閘門**（規格書 v1 漏掉的比對點）。24 個測試涵蓋全部 12 個 (Q,W) 格點（含 4 個會 wrap 的不安全格點）、4 個 D、4 個 clip，以及 GPU 編碼器與量化器的逐位元組比對。**零 mismatch。**
- `2026-07-14-19` test — C2′ 的測試證實真的碰到平手：單一組態就有 **85072 次** ACS 平手（Q=3 只有 8 階軟值）。`torch.minimum` 不回傳索引、`torch.argmin` 的平手行為沒有文件保證——這裡改用顯式的鍵 `d*64 + index`，不依賴任何未定義行為。
- `2026-07-14-20` debug — GPU 吞吐的兩次修正。(1) 激勵留在 CPU 時 GPU 空轉（numpy 產 3370 萬個高斯亂數 + 1030 次迭代的編碼迴圈），整體只有 6.7 Mb/s；把編碼器改寫成「移位視窗」一次算完並整段搬上 GPU。(2) survivor 打包成單一 int64 後吞吐從 38.5 **掉到 7.6 Mb/s**——消費級 GeForce 的 **int64 整數運算不是全速率**；改成兩個 int32，最終 **31 Mb/s**（B=32768，1.5 GB），約為 CPU golden 8-worker 總吞吐的 18 倍。
- `2026-07-14-21` test — **設計空間從 (Q, clip, W, D) 塌成 (Q, clip, D)**：W 不是 BER 的軸。這是 G6 的推論（modulo 決策等價 ⇒ 決策與 W 無關 ⇒ 解碼位元與 W 無關），且由 C2′ **直接比對解碼位元**驗證，不是假設。每個 Q 的最小安全 W 由字寬界唯一決定（3→8, 4→10, 5→10, 6→12），PPA 上沒有選擇餘地。
- `2026-07-14-22` test — 全網格 280 點掃完，64 個 (Q,clip,D) 組態全部有 1e-5 交叉點。**M1 的 C1 雜訊地板（±0.076 dB）已被解決**：M2 的 64 格損失全部為正（最小 +0.015 dB），不再有「量化贏過未量化」的物理不可能值。與 M1 交叉驗證：Q=3/clip=2.5σ/D=64 在 M2 量到 **+0.230 dB**，M1（獨立的 CPU 實作、不同亂數串流）量到 **+0.225 dB**。
- `2026-07-14-23` test — **G6 負向展示**：不安全格點的 BER **不降反升**。安全組態 (Q=4,W=10,D=32) 在 4.0→5.5 dB 掉 2.58 個數量級；不安全的 (Q=4,W=8) 在 4→7 dB 反而從 4e-4 **升到 5e-2**，(Q=5,W=8) 與 (Q=6,W=8) 直接釘在 **BER = 0.5（等同擲硬幣）**。機制：高 SNR 時軟值飽和到極值，branch metric 更常打到 λ_max，PM spread 變大 ⇒ wraparound ⇒ 比較反轉。比規格書預期的「高 SNR 神秘 floor」更尖銳。
- `2026-07-14-24` add — 選出 4 組 winner 並記錄理由。刻意**不造綜合成本分數**（真正的硬體成本要等 M5 合成，現在硬掰只會把假設偽裝成結論），改為沿著「所需 Eb/N0」與「已知支配面積的 survivor 記憶體 = 64×3D」挑點：最佳 BER (Q=6,clip=3.0,D=64, 4.152 dB)、最省記憶體 (Q=6,clip=3.0,D=32, 4.194 dB, 6144 bits)、最省 ADC/資料路徑 (Q=4,clip=2.5,D=64, 4.191 dB)、教科書組態 (Q=3,clip=2.0,D=32, 4.359 dB)。

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
