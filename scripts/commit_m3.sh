#!/usr/bin/env bash
set -eu
cd "$HOME/fec-cosim"

# 模擬與建置產物不入庫
for p in 'tb/cocotb/build/' 'tb/gl/vectors/' 'ppa/out/'; do
  grep -qxF "$p" .gitignore || echo "$p" >> .gitignore
done

git add -A
git commit -q -F - <<'MSG'
M3：RTL（full-parallel, register exchange）+ Tier A。C2 22,532 個 stage 零 mismatch

對外宣稱：**32 組 (Q,W,D) 組態 × 86 個 frame × 22,532 個 stage 比對，0 mismatch。**
每個 stage 比對 bm[4] / pm[64] / survivor[64] / 解碼位元，並在 stage_done 的脈衝上
觸發（不是靠數 cycle）——這也讓將來的折疊架構可以零成本沿用同一套 testbench。

RTL 依 docs/traceback_convention.md 的 uniform-depth-D 語意，採 register exchange
（教科書的批次 memory traceback 有效深度落在 [D, 2D]，解碼位元會與凍結文件不同）。
trellis 表由 RTL 自己從八進位多項式推導，**不從 L2 匯入**——共用一份表會讓表格 bug
變成 common-mode，C2 對它完全盲目。

C2 抓到的第一個 RTL bug，正是它存在的理由：

  traceback 被餵了**打拍後**的 survivor（上一個 stage 的），而 register exchange 的
  遞迴需要**這個 stage** 的。症狀極度陰險：bm / pm / survivor / best 全部完全正確，
  C2 對它們零 mismatch，**只有解碼位元在 frame 的頭尾錯掉**（256 個位元裡錯 3 個，
  位置 0, 254, 255）——因為高 SNR 下存活路徑很快收斂，中間的位元「剛好」還是對的。
  全零向量完全測不出來，是全一向量露出來的。

  **這就是「解碼位元必須納入 C2 比對集」的理由。** 只比 bm/pm/survivor 的話，
  這個 bug 會完整通過 C2，然後在 BER 上表現為「差一點點」而永遠找不到。

G6 的 assertion 也改對了。第一版讓影子 PM **跟著 RTL 的決策走**再量 spread——
那是錯的：wraparound 一發生，RTL 讓所有狀態都選到錯的分支，於是影子的 PM 全擠在
一個窄帶裡（Q=4/W=8 是 181~211），spread 從不變大，assertion 從不響。
正確的不變式是**決策等價**：影子必須自己做無界的正確決策，再比對 RTL 的 survivor。

G6 負向 4/4，全部在 stage 0 觸發：
  Q=4 W= 8  spread 181 > 128
  Q=5 W= 8  spread 382 > 128
  Q=6 W= 8  spread 808 > 128
  Q=6 W=10  spread 776 > 512
而且這些格點上 **C2 仍然零 mismatch**——RTL 與 golden 錯得一模一樣。
這本身就是 C2 有效性最強的佐證。

G7（4-state）：cocotb + Icarus 在本機走不通（oss-cad-suite 自帶的 glibc 撐不起
cocotb VPI 要 dlopen 的系統 libpython，裝系統版 iverilog 需要 root）。
改用**檔案驅動**的 SystemVerilog TB，Icarus 這一側完全不碰 Python。
10 個 frame / 2560 個位元，C2 零 mismatch 且輸出從未出現 X/Z => reset 是完整的。
同一支 TB 之後 M5 的 gate-level 模擬也會用到（cocotb 接不上 gate netlist）。

三重前端（Verilator 5.051 / Icarus 14.0 / Yosys 0.64）從第一個 RTL commit 起就跑。
過程中被 Yosys 以外的東西咬到：Verilator 把「// <它的名字> …」當成 pragma 解析，
一句中文註解就報錯；Icarus 不支援 always 區塊裡的 automatic 變數。

依 CLAUDE.md §4.1「MVP 先做對」：M3 只做 full-parallel（PAR=32）。
折疊架構（8-way / 1-way）是 PPA 的比較點，屬於 M5。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG

git tag -a m3-rtl -m "M3: C2 32 組 x 86 frames x 22,532 stages 零 mismatch；G6 負向 4/4；G7 通過"

git --no-pager log --oneline -5
echo ""
echo "tags: $(git tag -l | tr '\n' ' ')"
git status --short | head -3
echo "(空白 = 乾淨)"
