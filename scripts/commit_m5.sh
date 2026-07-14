#!/usr/bin/env bash
# M5 的提交：先把整條鏈路重跑一次（全綠才准 commit），再入庫、打 tag。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "=== 1. 重跑 M5 的閘門與機制分析（全綠才准 commit）"
python3 scripts/m5_gate.py > /tmp/m5_gate.txt 2>&1 || {
  echo "**m5_gate 失敗**"; tail -30 /tmp/m5_gate.txt; exit 1; }
grep -E "個 gate 全綠|FAIL" /tmp/m5_gate.txt | tail -2

python3 scripts/diag_mechanism.py > /tmp/m5_mech.txt 2>&1 || {
  echo "**diag_mechanism 失敗（有預測不成立）**"; tail -20 /tmp/m5_mech.txt; exit 1; }
tail -1 /tmp/m5_mech.txt

python3 ppa/saif_toggle.py > /tmp/m5_tog.txt 2>&1 || {
  echo "**saif_toggle 失敗**"; tail -20 /tmp/m5_tog.txt; exit 1; }
echo "  saif_toggle OK"

python3 scripts/plot_m5.py
echo

echo "=== 2. 入庫"
git add -A
echo "  新增/修改的檔案："
git diff --cached --name-only | sed 's/^/    /'
echo
echo "  入庫的 SAIF 證據（壓縮）："
du -ch $(git diff --cached --name-only | grep 'saif.gz' || true) 2>/dev/null | tail -1 | sed 's/^/    /'
echo

git -c user.name="$(git config user.name)" commit -q -F - <<'MSG'
M5：PPA + 能量模型。三條證偽條件全部不觸發，但我的 α 點估計錯了 3.4 倍

Gate-level 功耗 8 個點，SAIF annotation coverage 全部 100%。

裁決（docs/falsification.md §5，預先登記於任何量測之前）：
  F1  最小 d* = 17.8 m >> 1 m           -> 不觸發，d* 主張存活
  F2  模型 A 的 Δd*(Q3→Q6) = +11.3%/+6.3%  -> 不觸發，貢獻宣稱存活
  F3  符號 A 正、B 負，|A| < 30%         -> 不觸發
  §3.4 自稱「最咬得住」的「符號會翻轉」預測**確認成立**，
  且模型 B 的量級幾乎完全命中（事前 -0.87/-0.50%，實測 -0.75/-0.43%）。

但事前登記的 α ≈ 0.15，實測 α = 0.517 —— **錯了 3.4 倍**。兩個錯誤都是我的：
  1. 用 flop 數去估功耗佔比。traceback 佔 67.7-84.1% 的 flop，卻只佔 43.0-54.2%
     的功耗（ACS/min-PM 有大量組合邏輯，燒 switching power 但不是 flop）。
  2. 完全漏掉 min-PM 的 argmin 樹，而它同樣隨 W 縮放（+64.4%，超線性）。
誠實補充：falsification.md §3.2 的表本來就列了 α=0.50 那一列（+10.8/+6.1%），
實測正好落在那裡。**公式與符號推理都通過了；被推翻的只有點估計。**

規格書 §7 的「功耗 vs SNR 依賴曲線」交付物被實測推翻（風險 R1 成真）：
總功耗在 1→5 dB 只變動 1.0%、非單調、方向與前提相反。分區塊也救不了它。
依使用者裁定，改寫為負面結果 + 機制：

  量化器對稱 => r(c=1) = (2^Q-1) - r(c=0) == ~r(c=0)（位元互補）
  編碼位元 i.i.d. uniform => r 的每個位元在任何 SNR 下都以 0.5 翻轉
  Survivor 同理：正確的 survivor bit **就是 u[t-6]**，資訊位元本身
  => 完美的 Viterbi 解碼器與完全失效的，survivor 記憶體活動一模一樣
  => 唯一隨 SNR 動的是 pm（唯一不在最大熵的訊號，因為它是累加器），+3.3%

反事實（打破位元互補性）：bit1/bit2 的翻轉率從 0.504 崩到 0.000。機制成立。
這條機制我試錯了四輪（兩次是實驗設計寫壞），全部保留在 diag_mechanism.py。

意外發現：min-PM 的 argmin 樹佔 12-20% 面積，比整個 PM register file 還大
—— 這是 best-state traceback（而非 fixed-state）的直接代價。

Fmax：純邏輯合成的 netlist 上報 Fmax 沒有意義（166 ns / 6 MHz，但關鍵路徑是
一顆最小反相器扛 8683 個 sink / 18.1 pF）。OpenROAD repair_design 後 150.2 MHz，
4 個組態全部 >= 101 MHz > 100 MHz，能量模型的 f_clk 假設站得住。

PPA 表如實標註「僅 full-parallel（PAR=32）」。未做：折疊架構、post-route P&R、
memory traceback 對照、SRAM macro 版本。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG

git tag -f m5-ppa
echo
echo "=== 3. 完成"
git log --oneline | head -3
echo "  tag: $(git tag | tr '\n' ' ')"
