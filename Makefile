# Makefile —— 一鍵重跑的唯一入口。
#
# 每個 target 都只是薄薄一層，實際工作在 scripts/ 底下的 Python 驅動裡。
# 這樣做的理由（CLAUDE.md §5.4）：報告裡的每個數字都必須可由 script 重生。
# 把邏輯藏在 Makefile 的 shell 片段裡，等於讓那些數字失去可重生性。
#
# 所有 target 都先 source scripts/env.sh：Verilator/Icarus 來自 oss-cad-suite
# （$HOME/opt/oss-cad-suite），Python 來自專案的 .venv，兩者的 PATH 順序有講究
# （.venv 必須壓過 oss-cad-suite 自帶的 python）。

SHELL := /bin/bash
PY    := .venv/bin/python

.PHONY: help test env gates freeze sweep ber ppa report clean

help:
	@echo "fec-cosim —— K=7 soft Viterbi 的 bit-accurate co-simulation"
	@echo ""
	@echo "  make test     golden model 的正確性測試（暴力 ML、K=3 oracle、可重現性）"
	@echo "  make env      M0：工具鏈驗收（Verilator/Icarus、sm_120 GPU、gate-level 功耗流程）"
	@echo "  make gates    所有已上線的 known-answer 閘門，寫入 data/gates.csv"
	@echo "  make freeze   凍結 C2 的測試向量（輸入逐位元組 + 期望輸出的 SHA-256）"
	@echo "  make sweep    GPU 設計空間掃描 (Q, clip, W, D) x SNR"
	@echo "  make ber      Tier B 浸泡：解碼位元 XOR，零容忍"
	@echo "  make ppa      合成 -> gate-level sim -> SAIF -> OpenSTA 分區塊功耗 vs SNR"
	@echo "  make report   check_paper_numbers.py，必須輸出 mismatches: 0"
	@echo ""
	@echo "里程碑結束時跑 make gates，全綠才進下一階段（CLAUDE.md §4.2）。"

test:
	@source scripts/env.sh && $(PY) -m pytest tests/ -q

env:
	@source scripts/env.sh && $(PY) scripts/m0_gate.py

# M1 的閘門：G1、G2a、G2b、G3、G4，外加 C1 曲線與 D 軸資料。
# 依 gates.py 的紀律：任一 gate 失敗就不寫出任何 artifact，process 以 exit 2 結束。
gates: test
	@source scripts/env.sh && $(PY) scripts/m1_gate.py
	@source scripts/env.sh && $(PY) scripts/m2_gate.py
	@source scripts/env.sh && $(PY) scripts/m3_gate.py

freeze:
	@source scripts/env.sh && $(PY) scripts/freeze_vectors.py

# RTL 的三重前端檢查（Verilator / Icarus / Yosys）。從第一個 RTL commit 起就跑。
lint:
	@bash scripts/check_rtl.sh

# Tier A：C2 逐 stage 比對。MODE=c2 / g6neg
tier-a:
	@MODE=c2 bash scripts/tier_a.sh
	@MODE=g6neg bash scripts/tier_a.sh
	@bash scripts/g7_icarus.sh

sweep:
	@echo "M2 尚未開始"

ber:
	@echo "M4 尚未開始"

ppa:
	@source scripts/env.sh && bash ppa/smoke/run.sh

report:
	@echo "M6 尚未開始"

clean:
	rm -rf ppa/out/* obj_dir sim_build
	@echo "已清除模擬與合成產物。data/ 下的 CSV 與 SAIF 不動（那是證據）。"
