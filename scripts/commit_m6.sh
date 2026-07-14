#!/usr/bin/env bash
# M6 的提交：重跑整條 M5/M6 鏈路 + 變異測試，全綠才准 commit。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "=== 1. 重跑閘門（全綠才准）"
python3 scripts/m5_gate.py > /tmp/m6_gate.txt 2>&1 || {
  echo "**m5_gate 失敗**"; tail -20 /tmp/m6_gate.txt; exit 1; }
grep -E "個 gate 全綠" /tmp/m6_gate.txt

echo "=== 2. gates.csv 冪等性（再跑一次不得長出重複列）"
n1=$(wc -l < data/gates.csv)
python3 scripts/m5_gate.py > /dev/null 2>&1
n2=$(wc -l < data/gates.csv)
if [ "$n1" != "$n2" ]; then
  echo "**gates.csv 不是冪等的：$n1 -> $n2 列**"; exit 1
fi
echo "  OK：$n1 列，重跑後不變"

echo "=== 3. 機制分析（8 條預測全部成立才准）"
python3 scripts/diag_mechanism.py > /tmp/m6_mech.txt 2>&1 || {
  echo "**有預測不成立**"; tail -12 /tmp/m6_mech.txt; exit 1; }
tail -1 /tmp/m6_mech.txt

echo "=== 4. SAIF 翻轉分析 + 圖表"
python3 ppa/saif_toggle.py > /dev/null 2>&1
python3 scripts/plot_m5.py

echo "=== 5. 報告數字稽核"
python3 scripts/check_paper_numbers.py

echo
echo "=== 6. 變異測試（檢查器必須抓得到錯）"
bash scripts/mutate_check.sh 2>&1 | grep -E "結果：|檢查器"

echo
echo "=== 7. 入庫"
git add -A
git diff --cached --name-only | sed 's/^/    /'

git commit -q -F - <<'MSG'
M6：報告 + 數字稽核。144 條 assertion，mismatches: 0；變異測試 6/6

docs/report.md：每個數字都由 data/*.csv 現算。寫作順序刻意是「先跑
scripts/report_numbers.py、再照抄輸出」——反過來就是論文數字與資料脫節的標準死法。

移植 check_paper_numbers.py（自 RISC-V 專案），並補上一個上游沒有、
而本專案最需要的檢查：**預先登記的 commit 時間戳必須早於量測**。
實測 falsification.md / energy_model.md 於 ae9e151 (02:30:35) 加入，
功耗量測於 fabc105 (23:43:42) 加入 —— 早 21.2 小時，git 可驗證。
不機械化驗證這一條，「我們事前就登記了」就只是一句自稱。

變異測試（scripts/mutate_check.sh）注入 6 種已知錯誤，6/6 全部抓到。
它抓到 checker 的三個真洞，以及它自己的一個：

  1. coverage gap 不影響 exit code（上游把它當警告）。於是把 **17.8 m**
     改成 **19.9 m** 之後，因為 "17.8" 在結論散文裡還有一處沒被改到，
     「值須出現在文件中」照樣通過 —— CI 會綠燈放行一個被改壞的數字。
     已升級為 failure。
  2. 覆蓋掃描只掃百分比 -> 改為掃所有帶單位的數字。
  3. `\b` 不能加在 `%` 後面（兩個非字元之間沒有 word boundary），
     `42.7%。` 永遠比不到 —— 我自己「收緊」regex 時弄壞的。
  4. 變異測試自己也錯了：原本以 grep MISMATCH 當判準，但報告裡本來就有一個
     既存的 mismatch，於是每次都 grep 得到，四個變異全部假性「通過」。
     改為以 exit code 判準，並先確認乾淨狀態 exit 0。

data/gates.csv 有 29 列重複：finalize() 是 append（註解寫「保留歷史」），
但列裡沒有時間戳，那不是歷史是重複。改為以 (milestone, gate) 取代，
檔案變成冪等；56 列 -> 27 列，M0-M5 全綠。

自我更正三處（都是工具抓到的，不是人看出來的）：
  * min-PM 面積佔比 12.0% -> **11.8%**
  * min-PM/PM-regfile 倍數 2.2-2.5 -> **2.21-2.45**
  * pm「隨 SNR 單調上升」-> **非嚴格單調**（2 dB 有 0.3% 凹陷）。
    改用線性迴歸 R²，結論反而更強：pm 的 R² = 0.913，
    而 surv 的 R² = **0.000（與 SNR 零相關）**。
    並把「pm 單調上升」列入 checker 的已撤回主張防護，防止它悄悄復活。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG

git tag -f m6-report
echo
git log --oneline | head -3
echo "  tags: $(git tag | tr '\n' ' ')"
