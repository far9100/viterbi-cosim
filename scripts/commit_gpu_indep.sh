#!/usr/bin/env bash
set -eu
cd "$HOME/fec-cosim"

git add -A
git commit -q -F - <<'MSG'
C2' 不再硬相依 GPU：CPU 與 CUDA 兩條路都驗，且不可能因為「沒跑」而綠燈

起因是一個實務問題：GPU 被別的專案佔用（實測 3.5 GB / 100% 使用率），
本專案還能不能繼續？

答案是能——M2 的 GPU 工作已經做完並入庫（data/results_m2.csv、m2-sweep tag），
M3/M5/M6 完全不碰 GPU。但檢查的過程中發現一個真的漏洞：

C2' 的測試原本在沒有 CUDA 時整個檔案 skip。目前是靠 pytest 對「完全沒收集到測試」
回傳 exit code 5 才沒有出事——但那太脆弱：只要有人把 module-level skip 改成
per-test skip，pytest 就會回傳 0 加上「24 skipped」，而這道**零容忍**的閘門
會靜靜地綠燈。一道閘門不該因為「沒有跑」而看起來像通過。

兩層防護：
1. 測試改成 cpu / cuda 兩個裝置都跑。CPU 那一輪驗的是 torch 版的**邏輯**——
   平手方向、int32 溢位、位元打包的邊界、traceback 的切片索引——這些與 CUDA 無關，
   在 CPU 上就抓得到。有 GPU 時再額外驗 CUDA kernel 這條路。
2. 閘門明確要求「通過數 >= 22 且 skip = 0」，不只看 returncode，
   並如實揭露 CUDA 到底有沒有被驗到。

實測：有 GPU 時 47 passed；CUDA_VISIBLE_DEVICES='' 時 24 passed，閘門照樣綠，
但註明「CUDA 無 —— 只驗了 CPU 路徑」。

附帶觀察：在 GPU 被佔到 100% 的當下，C2' 跑 CUDA 要 60 秒，跑 CPU 只要 2 秒。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG

git --no-pager log --oneline -1
git status --short | head -3
echo "(空白 = 乾淨)"
