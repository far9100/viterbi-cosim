#!/usr/bin/env bash
# M0 的首次 commit。
set -eu
cd "$HOME/fec-cosim"

# 產物不入庫（.gitignore 已涵蓋），但 data/ 下的 gates.csv 與 metadata 是證據，要入庫。
git add -A

echo "=== 將要 commit 的檔案"
git status --short | sed 's/^/  /'

git commit -q -F - <<'MSG'
M0：環境建置、gate-level 功耗流程從零打通、規格書修訂

規格書 v1 把 Verilator、cocotb、OpenLane、以及「VCD/SAIF -> OpenSTA 功耗」
都當成既有資產。實測後這些前提都不成立：兩個模擬器與 torch 都沒安裝，
Windows 上連 g++ 都沒有，RISC-V 專案從未用過 OpenLane，而它的 gate-level power
是 vectorless 的假設值（activity=0.2/duty=0.5）——其論文自己把「workload SAIF 的
真實-activity EDP」列為未竟事項。功耗這一段沒有東西可以複用。

本次做完 M0 並修訂規格書：

- 工具鏈改用 oss-cad-suite（Verilator 5.051 + Icarus 14.0），免 root，
  同時省掉原計畫「apt + 從源碼編譯 Verilator」的 15 分鐘。
- torch 2.11.0+cu128 在 sm_120 上通過整數 ACS 與 numpy 的逐位元組比對。
  刻意檢查平手樣本數 > 0：torch.minimum 不回傳索引，survivor bit 要自己算，
  而 `<=` 與 `<` 的選擇會默默決定平手方向。這是 C2' 最可能的失效點。
- gate-level 功耗流程從零建置，以 8-bit counter 驗收，annotation coverage 100%。
  這條流程與解碼器毫無相依，卻是全專案唯一零複用、未知數最多的部分；
  第 1 週失敗還救得回來，第 5 週帶著 deadline 才發現 annotation 是 0% 就沒救了。
- 煙霧測試當場抓到 vcd2saif 的 timescale bug（跨行的 $timescale 比對失敗後
  靜默退回預設單位），它會讓所有功耗數字錯 1000 倍而不報任何錯。
  這正是先做煙霧測試的理由。

規格書的修訂（B1-B6）全部發生在任何量測開跑之前，並記錄於 docs/ 之下：
branch metric 改為非負距離度量（原本「相關度量取最大」與「torch.minimum 取最小」
自相矛盾）；G6 的字寬界補上初始化項；G2 改為兩段式嚴格 gate（union bound 是
可證明的上界，不是拍腦袋的容差）；SAIF 保留（gate-level VCD 是 30-180 KB/cycle，
不可能落地）；取消 rtl/sva/（Icarus 不支援 bind）。

docs/falsification.md 與 docs/energy_model.md 在任何量測前提交，
使預測的 commit 時間戳可驗證早於量測（CLAUDE.md §1.2）。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG

git tag -a m0-env -m "M0: 環境與 gate-level 功耗流程驗收通過（E1/E2/E3 全綠）"

echo ""
echo "=== commit"
git --no-pager log --oneline -1
git --no-pager show --stat --oneline HEAD | tail -n +2 | head -40
echo ""
echo "tag: $(git tag -l)"
