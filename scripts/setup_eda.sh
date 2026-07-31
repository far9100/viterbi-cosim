#!/usr/bin/env bash
# M0-5：安裝 RTL 模擬器（Verilator + Icarus），不需要 root。
#
# 為什麼用 oss-cad-suite 而不是 apt / 源碼編譯：
#
#   1. 這台機器的 sudo 需要密碼，agent 無法非互動地跑 apt。
#   2. apt 的 verilator 是 5.020（2023 年），與 cocotb 的 Verilator backend 有已知摩擦。
#   3. 從源碼編譯 Verilator 需要 flex/bison/autoconf/help2man —— 又繞回 apt。
#
# oss-cad-suite 是 YosysHQ 出的自帶相依單一 tarball：解壓縮到 $HOME 就能用，
# 一次拿到 Verilator（近期版）、Icarus Verilog、Yosys、GTKWave，完全不碰系統套件。
#
# 注意：它自帶一個 Python，會汙染 PATH。本專案只取它的 **binary**（verilator/iverilog），
# Python 一律用 .venv 的（cocotb 裝在那裡）。所以 environment 檔不整包 source，
# 只把 bin 目錄前置到 PATH，且放在 .venv 之後。
set -euo pipefail

DEST="$HOME/opt/oss-cad-suite"
CACHE="$HOME/.cache/oss-cad.tgz"

if [ -x "$DEST/bin/verilator" ] && [ -x "$DEST/bin/iverilog" ]; then
  echo "已安裝，略過下載。"
else
  # **釘住 release tag，不抓 latest。**
  #
  # 原本是查 GitHub 的 `releases/latest` —— 意思是**在不同的日子跑這支腳本會裝到
  # 不同版本的 Verilator 與 Icarus**。而 M3 的 C2、M4 的 2.47 億 stage 浸泡、
  # M5 與 M9 的閘級模擬全都由它們產生；模擬器換版本，那些結果就不再是同一件事，
  # 而 repo 裡沒有任何東西說得出當時裝的是哪一版。
  #
  # 現行環境實測是 Verilator 5.051 devel / Icarus 14.0 devel（見 data/meta_*.json），
  # 對應下面這個 tag。要升級：改 OSS_CAD_TAG，重跑 make gates 比對數字，並記進 CHANGELOG。
  OSS_CAD_TAG="${OSS_CAD_TAG:-2026-07-01}"
  echo "=== 取 oss-cad-suite $OSS_CAD_TAG（釘住的版本，非 latest）"
  BASE="https://github.com/YosysHQ/oss-cad-suite-build/releases/download"
  URL="$BASE/$OSS_CAD_TAG/oss-cad-suite-linux-x64-${OSS_CAD_TAG//-/}.tgz"
  if ! curl -fsSLI "$URL" >/dev/null 2>&1; then
    echo "FAIL: 釘住的 tarball 取不到：$URL"
    echo "  該 release 可能已被移除。確認要換版本之後，設 OSS_CAD_TAG 並記進 CHANGELOG。"
    exit 1
  fi
  echo "  $URL"

  echo "=== 下載（約 600 MB）"
  curl -fL --retry 3 -o "$CACHE" "$URL"

  echo "=== 解壓縮到 $HOME/opt"
  mkdir -p "$HOME/opt"
  rm -rf "$DEST"
  tar -xzf "$CACHE" -C "$HOME/opt"
fi

echo ""
echo "=== 版本"
export PATH="$DEST/bin:$PATH"
echo "  verilator: $(verilator --version 2>&1 | head -1)"
echo "  iverilog : $(iverilog -V 2>&1 | head -1)"
echo "  yosys    : $(yosys -V 2>&1 | head -1)"

# 讓後續所有 script 都能取用：寫一個可 source 的 env 檔。
# .venv 的 bin 放在 oss-cad-suite 之後，確保 python/pip 用的是專案 venv 而不是它自帶的。
cat > "$HOME/fec-cosim/scripts/env.sh" <<EOF
# 由 setup_eda.sh 產生。所有 script 開頭 source 這一支。
export OSS_CAD="$DEST"
export PATH="\$OSS_CAD/bin:\$PATH"
export PATH="\$HOME/fec-cosim/.venv/bin:\$PATH"   # 必須在 oss-cad-suite 之後，才能蓋掉它自帶的 python
EOF

echo ""
echo "已寫入 scripts/env.sh"
