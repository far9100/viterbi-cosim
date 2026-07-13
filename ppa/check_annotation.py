"""check_annotation.py — 從 OpenSTA 的輸出判定 activity annotation coverage 是否達標。

為什麼要有一支獨立的檢查器，而不是「人看一眼 log」：

annotation coverage 掉下來的時候，OpenSTA **不會報錯**。它會默默地對沒被標註的 net
套用 set_power_activity 的預設值（典型是 activity=0.1、duty=0.5），然後給你一個
看起來很正常的功耗數字。這個數字是猜的，而規格書 §7 明令禁止
「功耗不得用預設 toggle-rate 猜測」。

更糟的是它的症狀：ABC 映射出來的組合邏輯 net 名稱是 $abc$1234$new_n567 這種，
最容易對不上；而 Viterbi 的 SNR 依賴性**完全住在 ACS 的組合路徑上**。
組合 net 標註不到 -> 功耗-SNR 曲線依構造變平 -> 頭條結果報銷，而且沒有任何錯誤訊息。

所以 coverage 必須是一個會讓 build 失敗的硬性 gate，不是一個給人看的數字。

門檻（寫死，不得事後放寬）：
    >= 99%   通過。VCD 是這個 netlist 自己的 dump，每條 net 依定義都該存在，
             所以本來就該接近 100%。
    90-99%   警告。數字還能用，但必須在報告中揭露實際覆蓋率。
    < 90%    失敗。該功耗數字不足以宣稱「真實通道驅動」。
"""

import re
import sys

THRESHOLD_PASS = 99.0
THRESHOLD_WARN = 90.0


def parse(text):
    """從 report_activity_annotation 的輸出取出 annotated / total。

    OpenSTA 3.1.0 的實際格式（實測，不是猜的）是按「來源」分類計數的 pin 數：

        === ACTIVITY ANNOTATION ===
        saif          117
        unannotated     0
        Unannotated pins:

    也就是說它標註的單位是 **pin**，不是 net；每一行是一個 activity 的來源
    （saif / vcd / constant / clock / propagated / unannotated…）。
    覆蓋率 = 1 - unannotated / 全部。

    解析不到時必須明確失敗，不能預設通過——覆蓋率沒被確認過的功耗數字不可採信。
    """
    block = text
    m = re.search(r"=== ACTIVITY ANNOTATION ===(.*?)(?:===|\Z)", text, re.S)
    if m:
        block = m.group(1)

    counts = {}
    for line in block.splitlines():
        mm = re.match(r"\s*([A-Za-z_][A-Za-z_ ]*?)\s+(\d+)\s*$", line)
        if mm:
            counts[mm.group(1).strip().lower()] = int(mm.group(2))

    if not counts:
        return None, None

    unannotated = counts.pop("unannotated", None)
    if unannotated is None:
        return None, None

    annotated = sum(counts.values())
    return annotated, annotated + unannotated


def main():
    if len(sys.argv) < 2:
        print("用法: check_annotation.py <openSTA 的 log>")
        return 2

    with open(sys.argv[1]) as f:
        text = f.read()

    annotated, total = parse(text)

    if total is None:
        print("FAIL: 解析不到 report_activity_annotation 的輸出。")
        print("      這不代表通過——在確認覆蓋率之前，功耗數字不可採信。")
        print("      OpenSTA 的原始輸出：")
        for line in text.splitlines():
            if re.search(r"annotat|activity|power", line, re.I):
                print(f"        {line}")
        return 2

    pct = 100.0 * annotated / total if total else 0.0
    print(f"Activity annotation: {annotated} / {total} nets = {pct:.2f}%")

    if pct >= THRESHOLD_PASS:
        print(f"PASS: coverage {pct:.2f}% >= {THRESHOLD_PASS}%")
        print("      整條 gate-level 功耗流程打通：")
        print("      Yosys -> Icarus gate-level -> VCD -> SAIF -> OpenSTA")
        return 0

    if pct >= THRESHOLD_WARN:
        print(f"WARN: coverage {pct:.2f}% 落在 [{THRESHOLD_WARN}, {THRESHOLD_PASS}) —— "
              f"數字可用，但必須在報告中揭露實際覆蓋率")
        return 1

    print(f"FAIL: coverage {pct:.2f}% < {THRESHOLD_WARN}%")
    print("      功耗數字不足以宣稱「真實通道驅動的 switching activity」。")
    print("      最可能的原因（依機率排序）：")
    print("        1. read_saif 的 -scope 打錯（SAIF 的根是 tb/dut，設計的根是 top module）")
    print("        2. net 名稱對不上：向量展開（cnt[0]）或 escaped identifier 的跳脫方式")
    print("        3. VCD 的 $dumpvars 深度不夠，漏掉了 netlist 內部的 net")
    return 2


if __name__ == "__main__":
    sys.exit(main())
