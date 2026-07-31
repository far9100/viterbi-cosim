#!/usr/bin/env bash
# check_paper_numbers.py 的變異測試：一個抓不到錯的檢查器沒有價值。
# 逐一注入已知的錯誤（8 種），確認它**每一種都抓得到**。
#
# ## 為什麼是對副本操作（2026-07-31）
#
# 原本的做法是 `sed -i` 直接改 git 追蹤中的 docs/report.md，靠 `trap EXIT` +
# /tmp/report.bak 還原。但這支 script 是 `make all` 與 `make repro` 的**最後一步**，
# 跑在數小時的冷跑尾端——被 SIGKILL、/tmp 滿了、或機器重開，都會留下一份被改壞的
# 追蹤文件，而且看起來就像是有人手動改壞的。
#
# 現在把 report.md 複製到暫存目錄，只改副本，用 FEC_REPORT_PATH 把檢查器指過去。
# 真正的文件從頭到尾沒有被寫過一次，也就不需要還原機制。
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

R="$WORK/report.md"
cp docs/report.md "$R"
cp docs/report.md "$WORK/report.orig"

# 變異 7/8 要改的是**凍結文件**與勘誤索引，不能碰真本（那正是 §6 禁止的事）。
# 所以整個 docs/ 也複製一份，用 FEC_DOCS_ROOT 讓 §6 改讀副本；
# 對照用的凍結 blob 仍從真正的 repo 取，這樣「磁碟上的本體與凍結時不同」才驗得出來。
DR="$WORK/docsroot"
mkdir -p "$DR"
cp -r docs "$DR/docs"
cp -r "$DR/docs" "$WORK/docs.orig"

# 檢查器讀副本，其餘文件（falsification / spec / README）仍讀真本——
# 變異只注入在 report.md 與 docs/ 的副本，這正是要測的範圍。
check() {
  FEC_REPORT_PATH="$R" FEC_DOCS_ROOT="$DR" \
    python3 scripts/check_paper_numbers.py "$@"
}

pass=0
fail=0

# 判準是 **exit code**，不是 grep 字串。
#
# 第一版用 `grep -q MISMATCH` 當判準，結果被自己騙了：當時報告裡本來就有一個
# 既存的 mismatch（min-PM 倍數 2.5 vs 2.45），於是**每一次**都 grep 得到 MISMATCH，
# 四個變異全部「通過」——包括根本沒被抓到的那個。
# 所以先確認乾淨狀態 exit 0，再要求每個變異都讓 exit 變成非 0。
try() {
  local name="$1"
  if check > /tmp/mut.txt 2>&1; then
    echo "  **[漏掉]** $name  —— checker 竟然 exit 0"
    grep -E "mismatches|coverage" /tmp/mut.txt | head -2 | sed 's/^/        /'
    fail=$((fail+1))
  else
    echo "  [抓到] $name"
    grep -m1 "MISMATCH" /tmp/mut.txt | sed 's/^/        /'
    pass=$((pass+1))
  fi
  cp "$WORK/report.orig" "$R"
  rm -rf "$DR/docs" && cp -r "$WORK/docs.orig" "$DR/docs"
}

echo "=== 前置：乾淨狀態必須 exit 0（否則變異測試沒有意義）"
if check > /tmp/clean.txt 2>&1; then
  echo "  OK：乾淨狀態 exit 0"
else
  echo "  **乾淨狀態就已經 exit 1 —— 先修好報告再跑變異測試**"
  head -8 /tmp/clean.txt | sed 's/^/    /'
  exit 1
fi

echo
echo "=== 變異測試：注入已知錯誤，檢查器必須抓到（判準 = exit code 非 0）"

# 1. 只改**其中一處**引用（同一個值在別處還在，字串檢查會被騙過去）
#    這正是第一版漏掉的那種——只有擴大到「所有帶單位的數字」的覆蓋掃描才抓得到。
sed -i 's/\*\*17\.8 m\*\*/**19.9 m**/' "$R"
try "只改其中一處引用（d* 17.8 -> 19.9，別處仍有 17.8）"

# 2. 全部改掉（值與 CSV 不符）
sed -i 's/+11\.29%/+99.99%/g' "$R"
try "數字全部改掉（Δd* 11.29 -> 99.99）"

# 3. 已撤回的主張復活（R3）
sed -i 's/它是整條資料路徑上\*\*唯一不在最大熵\*\*的訊號/pm 隨 SNR 單調上升，它是唯一不在最大熵的訊號/' "$R"
try "已撤回的主張復活（pm「單調上升」）"

# 4. 新增一個沒被 assert 的百分比（覆蓋掃描）
sed -i 's/^## 6\. 一句話結論/## 5.9 新結果\n\n效率提升了 42.7%。\n\n## 6. 一句話結論/' "$R"
try "新增未被覆蓋的百分比（42.7%）"

# 5. 新增一個沒被 assert 的、帶單位的數字（覆蓋掃描的擴大版）
sed -i 's/^## 6\. 一句話結論/## 5.9 新結果\n\n量到 87.3 mW。\n\n## 6. 一句話結論/' "$R"
try "新增未被覆蓋的帶單位數字（87.3 mW）"

# 6. 靜默地把預先登記的引用改錯（跨文件比對）
sed -i 's/+10\.8% \/ +6\.1%/+33.3% \/ +44.4%/' "$R"
try "誤引預先登記的內容（+10.8%/+6.1% -> 捏造值）"

# 7. 就地改掉凍結文件的**本體**（§6a）
#    這是 CLAUDE.md §5.1 明令禁止的事，先前只靠紀律，沒有任何東西擋得住。
#    改一個字就必須紅燈——否則凍結文件的 commit 時間戳就不再描述它現在說的話。
sed -i 's/PM_INIT/PM_INIT_TAMPERED/' "$DR/docs/wordlength_bound.md"
try "凍結本體被就地改動（wordlength_bound.md）"

# 8. 勘誤索引與文件對不上（§6b）
#    加一列指向一份根本沒有勘誤帶的凍結文件。單向檢查會漏掉這種，
#    所以 §6 兩個方向都對帳。
printf '| E-99 | `docs/trellis_convention.md` | §1 | 捏造 | 捏造 | 無 | 無 |\n' \
  >> "$DR/docs/errata.md"
try "勘誤索引指向沒有勘誤帶的文件（E-99）"

echo
echo "=== 結果：抓到 $pass 種，漏掉 $fail 種"
[ "$fail" -eq 0 ] && echo "檢查器有效。" || echo "**檢查器有漏洞，必須修。**"

# 真正的 docs/report.md 從頭到尾沒被寫過；這裡直接對它跑一次，確認 0 mismatch。
echo
echo "=== 對真正的 docs/report.md"
python3 scripts/check_paper_numbers.py
rc=$?

# 工作區必須乾淨——如果變異測試曾經寫到追蹤檔，這裡會抓到。
if [ -n "$(git status --porcelain -- docs/report.md)" ]; then
  echo "**變異測試動到了 git 追蹤的 docs/report.md —— 這正是它不該做的事。**"
  exit 1
fi

[ "$fail" -eq 0 ] || exit 1
exit $rc
