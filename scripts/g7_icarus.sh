#!/usr/bin/env bash
# G7 —— Icarus（4-state）交叉檢查，不經過 cocotb / Python。
#
# Verilator 是 2-state 的：未初始化的暫存器讀出來是 0 而不是 X。一個 reset 不完整的 bug
# 在 Verilator 上會「剛好」是 0 而通過，在真實硬體與 Icarus 上卻是 X。
# 只有 4-state 的模擬器叫得出來。
#
# 為什麼不用 cocotb + Icarus：oss-cad-suite 的 vvp 自帶一整套 glibc（RPATH 指向自己的
# lib），而 cocotb 的 VPI 要 dlopen 系統的 libpython3.12，後者需要 GLIBC_2.38——
# oss-cad-suite 的 libm 太舊，直接爆掉。裝系統版 iverilog 需要 root（sudo 要密碼）。
# 繞法：Icarus 這一側完全不碰 Python，用 $readmemh 讀檔案驅動。
set -eu
cd "$HOME/fec-cosim"
# shellcheck disable=SC1091
source scripts/env.sh

OUT=ppa/out/g7
mkdir -p "$OUT"

echo "=== 匯出向量（golden 的期望輸出）"
.venv/bin/python scripts/export_vectors_hex.py

RTL="rtl/bmu.sv rtl/acs_butterfly.sv rtl/acs_array.sv rtl/minpm.sv
     rtl/traceback.sv rtl/ctrl.sv rtl/viterbi_top.sv"

FAIL=0
for V in directed_allzero directed_allone directed_impulse directed_burst \
         rand_Q4_W10_D32 boundary_Q4_W10; do
  # 這幾個向量都是 Q=4 W=10 D=32（見 vectors/MANIFEST.json）
  NF=$(.venv/bin/python -c "
import json,sys
m=json.load(open('tb/gl/vectors/index.json'))
print([x['n_frames'] for x in m if x['name']=='$V'][0])")

  # shellcheck disable=SC2086
  iverilog -g2012 -Irtl -o "$OUT/tb.vvp" \
    -DSIM_ICARUS \
    -Ptb_viterbi_file.Q=4 -Ptb_viterbi_file.W=10 \
    -Ptb_viterbi_file.D=32 -Ptb_viterbi_file.NINFO=256 \
    -s tb_viterbi_file $RTL tb/gl/tb_viterbi_file.sv 2> "$OUT/build.log"

  RES=$(vvp "$OUT/tb.vvp" \
          +stim=tb/gl/vectors/${V}_stim.hex \
          +dec=tb/gl/vectors/${V}_dec.hex \
          +frames="$NF" 2>&1 | grep 'TB_RESULT')

  if echo "$RES" | grep -q 'PASS'; then
    echo "  $V: $RES"
  else
    echo "  $V: $RES   <<< FAIL"
    FAIL=1
  fi
done

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "G7 通過：Icarus（4-state）下 C2 零 mismatch，且解碼輸出從未出現 X/Z。"
  echo "         => reset 是完整的，Verilator 的 2-state 沒有藏住任何東西。"
else
  echo "G7 失敗。"
fi
exit "$FAIL"
