"""dedup_gates.py — 一次性清掉 data/gates.csv 裡的重複列。

scripts/gates.py 的 finalize() 第一版是 append（註解寫「保留歷史」），但列裡沒有時間戳，
分不出哪一列來自哪一次 run —— 那不是歷史，是**重複**。實際後果：
m5_gate.py 跑了 6 次 -> 6 份一模一樣的 M5 gate；m2_gate.py 跑了 3 次 -> 3 份 M2。

gates.csv 是報告數字的**單一事實來源**（M6 的 check_paper_numbers.py 會讀它），
裡面有陳舊的重複列遲早會出事。

finalize() 已改為以 (milestone, gate) 取代。本檔把既有的檔案清乾淨（保留**最後**一次
出現的那一列 = 最新的量測），之後就靠 finalize() 維持冪等。
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.gates import DATA, GATES_FIELDS  # noqa: E402


def main():
    path = os.path.join(DATA, "gates.csv")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    # 保留每個 (milestone, gate) 的**最後**一次出現，但依**第一次**出現的順序排列
    order = []
    last = {}
    for r in rows:
        k = (r["milestone"], r["gate"])
        if k not in last:
            order.append(k)
        last[k] = r

    out = [last[k] for k in order]

    n_dup = len(rows) - len(out)
    print(f"原本 {len(rows)} 列 -> 去重後 {len(out)} 列（移除 {n_dup} 列重複）")

    by_ms = {}
    for r in out:
        by_ms.setdefault(r["milestone"], []).append(r)
    for ms in sorted(by_ms):
        n_fail = sum(1 for r in by_ms[ms] if r["passed"] != "True")
        print(f"  {ms}: {len(by_ms[ms])} 個 gate，"
              f"{'全綠' if not n_fail else f'**{n_fail} 個失敗**'}")

    n_fail = sum(1 for r in out if r["passed"] != "True")
    if n_fail:
        print(f"\n**{n_fail} 個 gate 不是 True —— 不寫檔。**")
        return 2

    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=GATES_FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f"\n-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
