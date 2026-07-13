# PPA 工具鏈的路徑常數。所有 PPA script 只從這裡取值，不在各處硬編碼。
#
# 這些路徑是 openroad/orfs:latest 容器**內部**的路徑，不是主機路徑。
# 以 `docker run ... --entrypoint /bin/bash openroad/orfs:latest -lc 'find / -name ...'` 實測確認。

ORFS_IMAGE   := openroad/orfs:latest

PLATFORM     := sky130hd
PDK_DIR      := /OpenROAD-flow-scripts/flow/platforms/$(PLATFORM)

LIB          := $(PDK_DIR)/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
TLEF         := $(PDK_DIR)/lef/sky130_fd_sc_hd.tlef
LEF          := $(PDK_DIR)/lef/sky130_fd_sc_hd_merged.lef

# 工具版本（實測，寫入 run metadata；CLAUDE.md §5.3 要求）
#   Yosys    0.64
#   OpenROAD 26Q3-23-gb65c274cad
#   OpenSTA  3.1.0（內建於 openroad，也有獨立的 `sta` binary）

# SRAM macro（M5 的 stretch goal）：survivor 記憶體是 64 bits x 3D 列，
# 而 image 內就有 64 bits x 256 列的 macro，3D <= 256 時尺寸正好對得上。
SRAM_64x256  := /OpenROAD-flow-scripts/flow/platforms/sky130ram/sky130_sram_1rw1r_64x256_8
