#!/usr/bin/env bash
# M1 的 commit 與凍結 tag。
set -eu
cd "$HOME/fec-cosim"

git add -A
echo "=== 將要 commit"
git status --short | sed 's/^/  /'

git commit -q -F - <<'MSG'
M1：L2 定點 golden model + K=7 浮點參考，G1-G4 全綠，測試向量凍結

規格書 v1 說「L1 = 既有 numpy 鏈路」。實測後不成立：既有模擬器只有 K=3 (7,5)、
4 狀態、硬編碼 trellis 的 Viterbi，branch metric 的簽名字面上就是兩個輸出位元。
K=7 是重寫，不是換參數。本次新寫 L1 浮點參考與 L2 定點 golden model。

L2 同時維護兩組 path metric：pm_mod（mod 2^W，C2 的比對標的，RTL 存的就是這個）
與 pm_ref（int64 無界）。每個 stage 斷言兩者導出的 ACS 選擇與 argmin 相同——
這才是 modulo normalization 正確性的證明，而不只是 spread 不等式。

三個自己的 bug，都是「不會報錯、只讓結果悄悄變爛」那一類：

1. 硬判決 branch metric 恆為 0 或 1、永遠到不了 2。numpy 對兩個 bool 陣列做 `+`
   是邏輯 OR，不是整數相加。解碼器分不出「錯一個位元」與「錯兩個位元」，
   等於不是 ML。自寫的暴力 ML 測試 10/10 通過（短 frame 蓋不到），
   是既有模擬器那份經過 mutation testing 的 K=3 oracle 在真實 frame 長度下抓到的。
   這正是「兩邊不能錯同一個錯」的價值——oracle 是獨立寫的，所以它抓得到我的錯。

2. BER 的亂數 seed 用 hash(str(cfg))，而 Python 對字串的 hash 每個 process 隨機加鹽。
   同一組態在不同 worker、不同次執行拿到不同 seed，結果不可重現。
   已改用 sha256，並加了跨 process 的重現性測試（同 process 內跑兩次抓不到）。

3. G2a/G4a 的判準本身寫錯：截斷過的 union bound 不是上界（硬判決的尾巴衰減得慢），
   而且拿有雜訊的估計值對確定的界做零容忍比較在統計上不成立。

閘門結果（99 個量測點，全部可由 make gates 重生）：
  G1  未編碼 BPSK @1e-5      9.571 dB   （容差 9.588 ±0.1）
  G2a 軟判決 vs union bound   最大 實測/界 0.981
  G2b 編碼增益 @1e-5          5.434 dB   （區間 [5.0, 5.6]）
  G3  3-bit 量化損失          0.225 dB   （容差 0.20 ±0.15，最佳 clip 2.5σ）
  G4a 硬判決 vs union bound   最大 實測/界 1.034
  G4b 硬判決損失              2.413 dB   （區間 [2.2, 2.7]，事後修正）

G2b 與 docs/falsification.md 在任何量測前登記的 5.39 dB 相符，
也證實規格書 v1 的 G2（5.0±0.3）確實會紅燈——那個修正是必要的，不是裝飾。

G4 則是量測之後才發現容差不可能達成：硬判決的 union bound（定理，獨立於本專案的量測）
就給出 2.355 dB，落在規格的 [1.7, 2.3] 之外。已如實標示為事後修正，
強度弱於 G2 的事前修正。

凍結 46 個 C2 測試向量（輸入逐位元組 + 期望輸出的 SHA-256）。
G6 的負向測試 4/4 於 stage 0 觸發，實測 PM spread 在每一格都低於最壞界卻高於 2^(W-1)
——證實那條界是充分非必要條件，且綁住字寬的是**初始化**而不是穩態。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG

git tag -a m1-golden -m "M1: L2 golden model 凍結。G1/G2a/G2b/G3/G4a/G4b 全綠，46 個 C2 測試向量凍結。此後才允許寫 RTL。"

echo ""
git --no-pager log --oneline -3
echo ""
echo "tags: $(git tag -l | tr '\n' ' ')"
echo ""
echo "=== 工作區"
git status --short | head -3
echo "(空白 = 乾淨)"
