#!/usr/bin/env bash
# 提交「把 Makefile 接上真正的 driver + README 納入稽核」。
# 冷跑（scripts/repro.sh）要求工作區乾淨，而且它驗的必須是**最終**的程式碼，所以先提交。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "=== 先確認全綠"
python3 scripts/m5_gate.py > /dev/null 2>&1 || { echo "**m5_gate 失敗**"; exit 1; }
make report
echo
bash scripts/mutate_check.sh 2>&1 | grep -E "結果：|檢查器"
echo

git add -A
git commit -q -F - <<'MSG'
把 Makefile 接上真正的 driver，並把 README 納入數字稽核

## Makefile 一度在說謊

  sweep:  echo "M2 尚未開始"     # M2 早就完成
  ber:    echo "M4 尚未開始"     # M4 早就完成
  report: echo "M6 尚未開始"     # M6 早就完成
  ppa:    只跑 M0 的 counter 煙霧測試，不是真的 PPA 流程
  gates:  只呼叫 m1/m2/m3_gate.py —— 漏掉 m4_gate.py 與 m5_gate.py

而 README 的「一鍵重跑」與規格書 §8 都宣稱這幾個指令能「從零重生所有數字與圖表」。
**那個宣稱當時是假的。** 所有 driver 都存在，Makefile 只是沒去呼叫它們。
這正是 CLAUDE.md §5.4 要守的東西，而工具本身沒兌現。

現在每個 target 都接上真正的 driver，另加 figures / mutate / all / repro。
續跑的 target（m2、m5）用 until 迴圈 + 快取，並有 GUARD 保險絲。

## README 停在 M3+M4 整整兩個里程碑都沒人發現

因為沒有任何東西在盯它。現在盯了：README 納入 check_paper_numbers.py
（190 條 assertion，含 M5/M6 的全部承重數字），而且

  * R3（已撤回主張的回歸防護）也掃 README
  * 帶單位的數字覆蓋掃描也掃 README
  * **自我指涉檢查**：README 說檢查器有幾條 assertion，就必須真的有幾條，
    而且**每一處**都要對（它提了三次）。這條會在每次新增 assertion 時壞掉——
    那正是它的用途：逼 README 跟著更新，而不是慢慢變成一句過期的自我吹噓。

## 順手修掉的兩個真洞

  1. M1 的數字（9.571 / 5.434 / 0.225 / 2.413）原本寫成 a(..., 9.571, 9.571)
     —— truth 與 cited 都是硬寫的常數，那條 assertion **只驗了「字串有出現」**，
     完全沒驗「它等於量測值」。改成從 gates.csv 的 measured 欄抽出真值。
  2. R3 的豁免區（<!-- R3-exempt -->）沒有數量限制。豁免會讓 R3 對其中的內容失明，
     可以被拿來把真正的違規靜音。改為全專案只准存在一個。

190 條 assertion / mismatches: 0；變異測試 6/6。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG

echo "=== 已提交"
git log --oneline | head -2
git status --short | head -3
echo "(工作區乾淨 = 可以開始冷跑)"
