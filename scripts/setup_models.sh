#!/usr/bin/env bash
# M0-7：取回 sky130_fd_sc_hd 的 cell models 並記錄 provenance。
#
# 為什麼需要：ORFS Docker image **不含**這些檔案（它只出貨 lib/lef/gds，從不模擬 gate），
# 但 gate-level VCD——功耗流程唯一可信的來源——必須模擬合成後的 netlist，那需要 cell 的行為模型。
#
# 為什麼**保留原始目錄結構**而不是攤平（第一次嘗試時踩到的坑）：
# 序向 cell 的模型用的是相對路徑 include：
#     sky130_fd_sc_hd__dfxtp.functional.v:34:
#         `include "../../models/udp_dff_p/sky130_fd_sc_hd__udp_dff_p.v"
# 相對路徑是相對於「包含它的那個檔案所在的目錄」解析的。一旦把所有 .v 攤平到同一層，
# ../../models/ 就指向不存在的地方，iverilog 直接在前處理階段失敗。
# 保留 cells/<name>/ 與 models/<name>/ 的相對位置，所有 include 就會自己解開。
set -euo pipefail

SRC="$HOME/.cache/sky130-src"
DEST="$HOME/fec-cosim/ppa/models"
TREE="$DEST/sky130_fd_sc_hd"

if [ ! -d "$SRC" ]; then
  echo "=== clone skywater-pdk-libs-sky130_fd_sc_hd（shallow）"
  git clone --depth 1 -q \
    https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd.git "$SRC"
fi

COMMIT=$(cd "$SRC" && git rev-parse HEAD)

rm -rf "$TREE"
mkdir -p "$TREE"

# 只取 .v，保留目錄結構。原始 repo 有 592 MB，但絕大多數是 JSON / SVG / timing 資料；
# .v 只有 9 MB 左右，適合 vendor 進 repo。
(cd "$SRC" && find cells models -name '*.v' -print0) \
  | (cd "$SRC" && tar --null -cf - --files-from=-) \
  | tar -xf - -C "$TREE"

N=$(find "$TREE" -name '*.v' | wc -l)
SZ=$(du -sh "$TREE" | cut -f1)
TREEHASH=$(cd "$TREE" && find . -type f -name '*.v' | sort | xargs sha256sum | sha256sum | cut -d' ' -f1)

cat > "$DEST/PROVENANCE.md" <<EOF
# sky130_fd_sc_hd cell models —— 來源與雜湊

Gate-level 模擬需要 cell 的行為模型。ORFS Docker image **不含**這些檔案（它只出貨
lib/lef/gds，從不模擬 gate），因此必須另外取回並入庫。這是本專案唯一一批 vendored 的
第三方原始碼。

| 項目 | 值 |
|---|---|
| 來源 | https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd |
| git commit | \`$COMMIT\` |
| 取回日期 (UTC) | $(date -u +%Y-%m-%d) |
| .v 檔案數 | $N |
| 大小 | $SZ |
| 內容雜湊 | \`$TREEHASH\` |

內容雜湊可重算：

\`\`\`bash
cd ppa/models/sky130_fd_sc_hd && find . -type f -name '*.v' | sort | xargs sha256sum | sha256sum
\`\`\`

## 目錄結構（不可攤平）

    ppa/models/sky130_fd_sc_hd/
    ├── cells/<cellname>/sky130_fd_sc_hd__<cellname>_<drive>.v   <- netlist 實例化的就是這些
    │                    sky130_fd_sc_hd__<cellname>.v            <- dispatcher
    │                    sky130_fd_sc_hd__<cellname>.functional.v
    └── models/udp_*/    sky130_fd_sc_hd__udp_*.v                 <- 序向 cell 的 UDP primitive

序向 cell 的 functional model 用**相對路徑** include UDP primitive
（\`../../models/udp_dff_p/...\`），所以 cells/ 與 models/ 的相對位置**必須保留**。
攤平會讓 iverilog 在前處理階段就失敗。

## 編譯時的 define

| define | 設定 | 理由 |
|---|---|---|
| \`USE_POWER_PINS\` | **不定義** | Yosys 產出的 netlist 沒有 power pin；定義了會 port 數不符。 |
| \`FUNCTIONAL\` | **定義** | 選 \`.functional.v\`。不定義會選 \`.behavioral.v\`，那裡的 \`specify\` block 需要 SDF 反標註才有意義。 |
| \`UNIT_DELAY\` | \`#1\` | 給每個 cell 一個時間單位的延遲，讓結構性 hazard（glitch）能傳播。零延遲模擬完全沒有 glitch，會系統性低估動態功耗。 |

**已知偏差**：UNIT_DELAY 不是真實 SDF 標註的延遲，glitch 行為只是近似。方向不明，
已記錄於 \`docs/energy_model.md\` §6。
EOF

echo "FILES=$N"
echo "SIZE=$SZ"
echo "COMMIT=$COMMIT"
echo "TREEHASH=$TREEHASH"
