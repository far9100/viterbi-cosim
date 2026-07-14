#!/usr/bin/env bash
# 把冷跑（repro.sh）**脫離 process tree** 跑起來。
#
# 為什麼：harness 對指令有 10 分鐘的上限，超過就砍掉。冷跑要 2-4 小時
# （M1 的 BER + M2 的 GPU 掃描是大宗，M5 的 gate-level 功耗實測 35.4 分）。
# setsid + nohup 讓它成為獨立的 session leader，呼叫者被砍時它不會被連坐。
#
# 進度寫進 /tmp/repro.log，輪詢即可。完成時寫出 /tmp/repro.done（內容是 exit code）。
set -eu
cd "$HOME/fec-cosim"

LOG=/tmp/repro.log
DONE=/tmp/repro.done
rm -f "$LOG" "$DONE"

setsid nohup bash -c "
  bash scripts/repro.sh > '$LOG' 2>&1
  echo \$? > '$DONE'
" > /dev/null 2>&1 < /dev/null &

sleep 2
echo "冷跑已在背景啟動（脫離 process tree）"
echo "  log:  $LOG"
echo "  完成時寫出 $DONE（內容是 exit code）"
echo
echo "--- 目前的輸出 ---"
head -30 "$LOG" 2>/dev/null || echo "(還沒有輸出)"
