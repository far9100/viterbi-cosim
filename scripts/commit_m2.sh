#!/usr/bin/env bash
set -eu
cd "$HOME/fec-cosim"

# M2 的量測快取不入庫（可重生）；資料來源是 data/results_m2.csv
grep -q 'cache_m2' .gitignore || echo 'data/cache_m2/' >> .gitignore

git add -A
git commit -q -F - <<'MSG'
M2：GPU 掃描 + C2' 位元級相等，設計空間塌成 (Q, clip, D)

C2' 是規格書 v1 漏掉的比對點。GPU 版的 golden model 會產生 Tier B 的期望輸出、
也會決定 winner 組態——它若與 CPU golden 差一個 bit，C2 就失去意義（RTL 對的是
一份錯的參考）。24 個測試涵蓋全部 12 個 (Q,W) 格點（含 4 個會 wrap 的不安全格點）、
4 個 D、4 個 clip，外加 GPU 編碼器與量化器的逐位元組比對。零 mismatch。

C2' 抓的是這種東西：torch.minimum 不回傳索引，survivor bit 得自己算，而 `<=` 與 `<`
的選擇會默默決定平手方向。單一組態就有 85072 次 ACS 平手（Q=3 只有 8 階軟值）。
torch.argmin 的平手行為在文件上也沒有保證，所以改用顯式的鍵 d*64+index。

設計空間從 (Q, clip, W, D) 塌成 (Q, clip, D)：W 不是 BER 的軸。這是 G6 的推論
（modulo 決策等價 => 決策與 W 無關 => 解碼位元與 W 無關），而且是**驗證**過的，
不是假設——C2' 直接比對解碼位元。每個 Q 的最小安全 W 由字寬界唯一決定，
PPA 上沒有選擇餘地。

兩次效能修正：
1. 激勵留在 CPU 時 GPU 空轉（numpy 產 3370 萬個高斯亂數 + 1030 次迭代的編碼迴圈），
   整體只有 6.7 Mb/s。把編碼器改寫成「移位視窗」一次算完，整段搬上 GPU。
2. survivor 打包成單一 int64 後吞吐從 38.5 掉到 7.6 Mb/s——消費級 GeForce 的
   int64 整數運算不是全速率。改成兩個 int32，最終 31 Mb/s（CPU 8-worker 的 18 倍）。

結果：
- 全網格 280 點，64 個 (Q,clip,D) 組態全部有 1e-5 交叉點。
- M1 的 C1 雜訊地板（±0.076 dB）已解決：M2 的 64 格損失全部為正（最小 +0.015），
  不再有「量化贏過未量化」的物理不可能值。
- 與 M1 交叉驗證：Q=3/clip=2.5/D=64 在 M2 是 +0.230 dB，M1（獨立的 CPU 實作、
  不同亂數串流）是 +0.225 dB。
- G6 負向展示：不安全格點的 BER **不降反升**。(Q=4,W=8) 在 4->7 dB 從 4e-4 升到 5e-2；
  (Q=5,W=8) 與 (Q=6,W=8) 直接釘在 BER=0.5（等同擲硬幣）。比規格書預期的
  「高 SNR 神秘 floor」更尖銳——因為 PM_INIT 本身就放不進 W bits，stage 0 就壞了。
- 4 組 winner，理由已記錄。刻意不造綜合成本分數：真正的硬體成本要等 M5 合成，
  現在硬掰只會把假設偽裝成結論。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG

git tag -a m2-sweep -m "M2: C2' 零 mismatch，280 點全網格，4 組 winner"

git --no-pager log --oneline -4
echo ""
echo "tags: $(git tag -l | tr '\n' ' ')"
git status --short | head -3
echo "(空白 = 乾淨)"
