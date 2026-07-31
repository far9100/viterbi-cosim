# Makefile —— 一鍵重跑的唯一入口。
#
# 每個 target 都只是薄薄一層，實際工作在 scripts/ 與 ppa/ 底下的 driver 裡。
# 這樣做的理由（CLAUDE.md §5.4）：報告裡的每個數字都必須可由 script 重生。
# 把邏輯藏在 Makefile 的 shell 片段裡，等於讓那些數字失去可重生性。
#
# 所有 target 都先 source scripts/env.sh：Verilator/Icarus 來自 oss-cad-suite
# （$HOME/opt/oss-cad-suite），Python 來自專案的 .venv，兩者的 PATH 順序有講究
# （.venv 必須壓過 oss-cad-suite 自帶的 python）。
#
# ## 2026-07-15 的修訂（重要）
#
# 這份 Makefile 一度在**說謊**：`sweep` / `ber` / `report` 分別印出
# 「M2 / M4 / M6 尚未開始」——而三者早就完成；`ppa` 只跑 M0 的 counter 煙霧測試；
# `gates` 漏掉 `m4_gate.py` 與 `m5_gate.py`。
# 而 README 與規格書 §8 都宣稱這幾個指令能「從零重生所有數字與圖表」。
# **那個宣稱當時是假的。** 所有 driver 都存在，Makefile 只是沒去呼叫它們。
#
# 現在每個 target 都接上真正的 driver，而且 `make repro` 會**真的把 data/ 刪光重生**，
# 用 `git status` 逐位元組驗證那個宣稱。

SHELL := /bin/bash
PY    := .venv/bin/python
ENV   := source scripts/env.sh &&

# 續跑用的時間片。grid_runner 與 run_power 都會在預算用盡時「乾淨結束並回傳 1」，
# 落好快取，重複呼叫即可接著跑。GUARD 是跑掉的迴圈的保險絲。
BUDGET ?= 420
GUARD  ?= 60

.PHONY: help test env m1 freeze m2 sweep m3 m4 ber m5 ppa fmax figures \
        gates report mutate all repro lint tier-a clean distclean \
        m9 m9-verify m9-sweep m9-null

help:
	@echo "fec-cosim —— K=7 soft Viterbi 的 bit-accurate co-simulation"
	@echo ""
	@echo "  逐里程碑："
	@echo "    make env       M0：工具鏈驗收（Verilator/Icarus、GPU、gate-level 功耗流程）"
	@echo "    make m1        M1：L2 golden model + G1-G4（~1 小時，8 workers，可續跑）"
	@echo "    make freeze    凍結 C2 的測試向量（SHA-256）"
	@echo "    make m2        M2：GPU 設計空間掃描 + C2'（可續跑）"
	@echo "    make m3        M3：RTL + Tier A（C2 / G6 正反向 / G7）"
	@echo "    make m4        M4：Tier B 浸泡（2.47 億個 stage）"
	@echo "    make m5        M5：合成 -> gate-level -> SAIF -> OpenSTA -> d*（~50 分，可續跑）"
	@echo "    make m9        M9：低功耗基準線 B0/B0'/B1'（先過 C2 才量功耗，~2.5 小時，可續跑）"
	@echo ""
	@echo "  交付："
	@echo "    make figures   重生所有圖表"
	@echo "    make report    check_paper_numbers.py（須 mismatches: 0）"
	@echo "    make mutate    變異測試：檢查器必須抓得到錯（6/6）"
	@echo ""
	@echo "  整條鏈路："
	@echo "    make all       env -> m1 -> m2 -> m3 -> m4 -> m5 -> m9 -> figures -> report"
	@echo "    make repro     **冷跑**：刪光 data/ 從零重生，git status 必須只剩 meta_*.json"
	@echo ""
	@echo "  別名：sweep=m2  ber=m4  ppa=m5"
	@echo ""
	@echo "  可續跑的 target（m2 / m5 / m9）吃兩個變數："
	@echo "    BUDGET=$(BUDGET)   單趟的秒數預算，用盡就落快取、乾淨結束"
	@echo "    GUARD=$(GUARD)     續跑輪數上限（保險絲，避免真正的失敗變成無窮迴圈）"
	@echo ""
	@echo "里程碑結束時跑該里程碑的 gate，全綠才進下一階段（CLAUDE.md §4.2）。"

# ---------------------------------------------------------------- 單元測試
test:
	@$(ENV) $(PY) -m pytest tests/ -q

# ---------------------------------------------------------------- M0
# m0_gate.py 自帶 counter 的全流程煙霧測試（Yosys -> Icarus -> VCD -> SAIF -> OpenSTA）
env:
	@$(ENV) $(PY) scripts/m0_gate.py

# ---------------------------------------------------------------- M1
# m1_gate.py 自己就是量測（Pool(8) + data/cache_m1），跑完直接寫 gate。
# 約 1 小時；被中斷也沒關係，快取讓它接著跑。
m1: test
	@$(ENV) $(PY) scripts/m1_gate.py

freeze:
	@$(ENV) $(PY) scripts/freeze_vectors.py

# ---------------------------------------------------------------- M2
# grid_runner 在 BUDGET 用盡時乾淨結束並回傳 1（快取已落地）；迴圈直到它回傳 0。
# GUARD 是保險絲：真正的失敗（例如 GPU 不見了）不該變成無窮迴圈。
m2:
	@$(ENV) i=0; \
	  until BUDGET=$(BUDGET) $(PY) sweep/grid_runner.py; do \
	    i=$$((i+1)); \
	    if [ $$i -ge $(GUARD) ]; then echo "**grid_runner 續跑超過 $(GUARD) 輪，中止**"; exit 1; fi; \
	  done
	@$(ENV) $(PY) scripts/m2_gate.py
sweep: m2

# ---------------------------------------------------------------- M3
# m3_gate.py 自己會呼叫 check_rtl.sh 與 tier_a.sh（MODE=c2 / g6neg）與 g7_icarus.sh
m3:
	@$(ENV) $(PY) scripts/m3_gate.py
lint:
	@bash scripts/check_rtl.sh
tier-a:
	@MODE=c2 bash scripts/tier_a.sh
	@MODE=g6neg bash scripts/tier_a.sh
	@bash scripts/g7_icarus.sh

# ---------------------------------------------------------------- M4
m4:
	@$(ENV) $(PY) scripts/tier_b.py
	@$(ENV) $(PY) scripts/m4_gate.py
ber: m4

# ---------------------------------------------------------------- M5
# synth -> gate-level 功耗（可續跑）-> STA(Fmax) -> SAIF 翻轉分析 -> 機制 -> 歸檔 -> gate
m5:
	@$(ENV) $(PY) ppa/synth.py
	@$(ENV) i=0; \
	  until $(PY) ppa/run_power.py; do \
	    i=$$((i+1)); \
	    if [ $$i -ge $(GUARD) ]; then echo "**run_power 續跑超過 $(GUARD) 輪，中止**"; exit 1; fi; \
	  done
	@$(ENV) $(PY) ppa/sta.py
	@$(ENV) $(PY) ppa/saif_toggle.py
	@$(ENV) $(PY) scripts/diag_mechanism.py
	@bash scripts/saif_archive.sh m5
	@$(ENV) $(PY) scripts/m5_gate.py
ppa: m5
fmax:
	@$(ENV) $(PY) ppa/sta.py

# ---------------------------------------------------------------- 交付
# ---------------------------------------------------------------- M9：低功耗基準線
#
# 順序不可顛倒（docs/lowpower_baseline.md §4.1）：**先過 C2，才准量功耗**。
# clock gating 的第一版正是死在 C2 —— ICG 關掉時脈時同步 reset 進不去，
# 而症狀偽裝成「收到 0 個輸出」，功耗流程照樣會產出漂亮的數字。
m9-verify:
	@$(ENV) $(PY) ppa/verify_cg.py

# m9_sweep（32 個閘級點）與 m9_null（16 個）都會在預算用盡時乾淨結束並回傳 1，
# 快取已落地，重複呼叫即可接著跑——與 m2 / m5 同一個 until 樣板。
m9-sweep: m9-verify
	@$(ENV) i=0; \
	  until $(PY) scripts/m9_sweep.py; do \
	    i=$$((i+1)); \
	    if [ $$i -ge $(GUARD) ]; then echo "**m9_sweep 續跑超過 $(GUARD) 輪，中止**"; exit 1; fi; \
	  done

m9-null:
	@$(ENV) i=0; \
	  until $(PY) scripts/m9_null.py; do \
	    i=$$((i+1)); \
	    if [ $$i -ge $(GUARD) ]; then echo "**m9_null 續跑超過 $(GUARD) 輪，中止**"; exit 1; fi; \
	  done

m9: m9-sweep m9-null
	@bash scripts/saif_archive.sh m9
	@$(ENV) $(PY) scripts/m9_gate.py

figures:
	@$(ENV) $(PY) scripts/plot_m1.py
	@$(ENV) $(PY) scripts/plot_m2.py
	@$(ENV) $(PY) scripts/plot_m5.py
	@$(ENV) $(PY) scripts/plot_pareto.py
	@$(ENV) $(PY) scripts/plot_m9.py

# 所有已上線的 known-answer 閘門 -> data/gates.csv
#
# 第一版漏掉 m4 與 m5——那正是這份 Makefile 之前在說謊的一部分。
# 第二版漏掉 m0 與 m9：`gates.py` 的 finalize() 是**以 milestone 為單位整批取代**，
# 所以沒被列進來的里程碑，它的列只會沿用檔案裡的舊值、永遠不會被重新驗證。
# gates.csv 有 36 列，而這個「跑全部 gate」的入口當時只涵蓋其中 25 列。
gates:
	@$(ENV) $(PY) scripts/m0_gate.py
	@$(ENV) $(PY) scripts/m1_gate.py
	@$(ENV) $(PY) scripts/m2_gate.py
	@$(ENV) $(PY) scripts/m3_gate.py
	@$(ENV) $(PY) scripts/m4_gate.py
	@$(ENV) $(PY) scripts/m5_gate.py
	@$(ENV) $(PY) scripts/m9_gate.py

report:
	@$(ENV) $(PY) scripts/check_paper_numbers.py

# 一個抓不到錯的檢查器沒有價值。注入 6 種已知錯誤，必須每一種都抓到。
mutate:
	@bash scripts/mutate_check.sh

# m9 必須排在 figures 之前：plot_m9.py 讀 data/power_m9.json 與 data/power_m9_null.json，
# 而冷跑會把 data/ 刪光。M9 不在鏈路裡的話，`make figures` 就會在冷跑中途 FileNotFoundError。
all: env m1 freeze m2 m3 m4 m5 m9 figures report mutate
	@echo ""
	@echo "整條鏈路完成。"

# **冷跑**：刪光 data/ 從零重生，並用 git status 逐位元組驗證。
# 這是規格書 §8 的宣稱——在 2026-07-15 之前它從來沒有被測試過。
repro:
	@bash scripts/repro.sh

# ---------------------------------------------------------------- 清理
clean:
	rm -rf ppa/out/* obj_dir sim_build tb/cocotb/build
	@echo "已清除模擬與合成產物（含 cocotb 的 pass-marker）。data/ 下的 CSV 與 SAIF 不動（那是證據）。"

# distclean 連證據一起刪 —— 只有 repro 該用它，所以要你手動確認。
distclean:
	@echo "這會刪掉 data/（含 CSV 與 SAIF 證據）、ppa/out/、figures/。"
	@echo "git 追蹤的檔案可以用 'git checkout -- data/' 救回；快取與原始 .saif 不行（要重跑）。"
	@echo "要做這件事請跑 'make repro'（它會先備份）。"
	@exit 1
