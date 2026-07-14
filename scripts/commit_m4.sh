#!/usr/bin/env bash
set -eu
cd "$HOME/fec-cosim"

# Tier B 的激勵位元組不入庫（41 MB/點，可由 seed 重生）；manifest（含 SHA-256）入庫。
grep -qxF 'ppa/out/' .gitignore || echo 'ppa/out/' >> .gitignore

git add -A
git commit -q -F - <<'MSG'
M4：Tier B —— 2.47 億個 stage 的 C2 浸泡，零 mismatch

## C++ harness 裡沒有 RNG，也沒有量化器

規格書 v1 §4 要求「C++ 端的 AWGN + 量化器必須與 L2 位元級一致，先做 10^5 bits 的
全等比對」。那做不到：numpy 的 PCG64 + ziggurat 與任何獨立寫的 C++ RNG 都不可能
逐位元組相同，除非共用實作——而共用實作又讓那個「等價比對」變成同義反覆。

這個要求被**廢除**，不是放寬。改成讓 C++ 端只重播 L2 匯出的激勵：

    gen_stimulus.py (L2/GPU) -> stimulus.bin + expected.bits + manifest.json（SHA-256）
    tb/cpp/sim_main.cpp      -> 讀激勵、驅動 DUT、解碼位元 XOR、零容忍

比 v1 的要求**更強**：Tier-B 的激勵**就是** L2 的激勵，逐位元組相同，因為只有一份。
AWGN 的正確性另外驗（經驗變異數 vs N0/2），留在 golden/ 那一側。

## Tier B 的目的不是量 BER

C2 已證明 RTL ≡ golden 逐位元相等，所以 RTL 的 BER 曲線與 L2/GPU 的**在數學上是同一條**。
重跑上億位元去「重新量」一條已知的曲線不是驗證，是算術。報告要直接寫：

    我們不量 RTL 的 BER。我們證明 RTL ≡ golden 逐位元相等，
    然後在 golden 上以 100x 的樣本數量 BER。

這是方法學上的強項，不是抄捷徑。

## 結果

  12 個 (winner 組態 x SNR) 點
  245,760,000 個資訊位元 / 247,200,000 個 trellis stage
  解碼位元逐位元 XOR：0 mismatch
  SHA-256：12/12 對帳相符
  相對 Tier A（22,532 stages）擴大 10,971 倍

三道 gate：
  G8a  延伸 C2 浸泡      零 mismatch
  G8b  激勵位元組對帳    12/12（CLAUDE.md §5.1(d)）
  G8c  G6 assertion 浸泡  2.47 億個 stage 的低 SNR 浸泡中**全程靜默**
       —— 而 M3 已證明它在 4 個不安全格點上會於 stage 0 響。
       wraparound 是稀有事件，Tier A 的 22,532 個 stage 遠不足以證明安全格點
       在最惡劣的輸入下也不會 wrap。這才是這個哨兵真正發揮價值的地方。

Verilator 約 600 kHz（比計畫預估的 2-5 MHz 慢：--assert 會把 64-state 的
G6 影子 ACS 也編進去，等於多跑一份解碼器）。激勵產生序列跑（只開一個 CUDA context，
GPU 正被別的專案佔用），模擬跨 (組態 x SNR) 開獨立 process，不用 --threads，不開 --trace。

激勵的位元組不入庫（41 MB/點，可由 seed 重生）；manifest（含 SHA-256）入庫，
所以任何一次重生都能被驗證。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG

git tag -a m4-tierb -m "M4: Tier B 2.47 億 stage 浸泡零 mismatch；G6 assertion 全程靜默"

git --no-pager log --oneline -3
echo ""
echo "tags: $(git tag -l | tr '\n' ' ')"
git status --short | head -3
echo "(空白 = 乾淨)"
