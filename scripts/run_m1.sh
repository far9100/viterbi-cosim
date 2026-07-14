#!/usr/bin/env bash
# 把 M1 閘門完全脫離呼叫者的 process tree 跑起來。
#
# 為什麼要這樣：harness 對背景指令有 10 分鐘的上限，超過就砍掉。M1 的量測
# （~90 個 (組態 x SNR) 點，每點最多 50 秒）會超過。setsid + nohup 讓它成為
# 獨立的 session leader，呼叫者被砍時它不會被連坐，進度寫進 log 檔供輪詢。
set -eu
cd "$HOME/fec-cosim"
# shellcheck disable=SC1091
source scripts/env.sh

LOG="data/m1_gate.log"
mkdir -p data
rm -f "$LOG" data/m1_gate.done

setsid nohup bash -c "
  .venv/bin/python scripts/m1_gate.py > '$LOG' 2>&1
  echo \$? > data/m1_gate.done
" > /dev/null 2>&1 < /dev/null &

echo "M1 閘門已在背景啟動（脫離 process tree）"
echo "  log:  ~/fec-cosim/$LOG"
echo "  完成時會寫出 data/m1_gate.done（內容是 exit code）"
