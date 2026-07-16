"""gates.py — 閘門框架：任一 gate 失敗就不寫出任何 artifact，且 process 以非零碼結束。

## 為什麼是這個設計

沿用既有通訊模擬器 `experiments/_gate.py` 的紀律，那是那個專案裡最強的一條慣例：

    gate.csv(path, fields, rows)   # 只是排隊，不寫檔
    gate.check(label, passed, detail)
    gate.finalize()                # 唯一的出口

**只要有任何一個 check 失敗，finalize() 就一個檔案都不寫，並且 exit 2。**

理由：半綠的資料比沒有資料更危險。一個 gate 紅燈、但 CSV 照樣落地的專案，
最後一定會有人（包括未來的自己）拿那份 CSV 去畫圖、去寫報告，而忘了它是紅燈下產生的。
把「寫檔」和「全綠」綁死，是唯一能杜絕這件事的做法。

## 與 CLAUDE.md 的關係

- §4.2：每個里程碑結束要跑一次 `make gates`，全綠才進下一階段。
- §5.4：報告裡的每個數字都必須存在於 data/results.csv 或 data/gates.csv，
        且可由 scripts/ 底下的 script 重生。
- §5.3：每一次量測都必須記錄可重現所需的完整 metadata。本檔負責寫 metadata 那一份。
"""

import csv
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")

GATES_FIELDS = [
    "gate", "passed", "measured", "expected", "tolerance", "detail", "milestone",
]


def _git(*args):
    try:
        return subprocess.check_output(
            ["git", "-C", REPO, *args], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def collect_metadata(extra=None):
    """收集重現這次 run 所需的全部資訊（CLAUDE.md §5.3）。

    為什麼要這麼囉唆：前一個專案吃過虧——有個純量的分析參數沒進 metadata，
    事後完全無法追溯或對帳。一個無法追溯到 (seed, 組態, commit) 的 BER 點不是證據。
    """
    md = {
        "start_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "argv": sys.argv,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "python": sys.version.split()[0],
    }
    try:
        import numpy
        md["numpy"] = numpy.__version__
    except ImportError:
        pass
    for tool, args in (("verilator", ["--version"]), ("iverilog", ["-V"])):
        try:
            out = subprocess.check_output([tool, *args], stderr=subprocess.STDOUT)
            md[tool] = out.decode().splitlines()[0].strip()
        except Exception:
            md[tool] = "absent"
    if extra:
        md.update(extra)
    return md


class Run:
    """一次量測 run。所有 artifact 先排隊，全綠才落地。"""

    def __init__(self, name, milestone):
        self.name = name
        self.milestone = milestone
        self.checks = []      # (label, passed, measured, expected, tol, detail)
        self.pending = []     # (path, fields, rows)
        self.metadata = collect_metadata({"run": name, "milestone": milestone})

    def check(self, label, passed, measured="", expected="", tolerance="", detail=""):
        self.checks.append((label, bool(passed), measured, expected, tolerance, detail))
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {label:<28} {measured}  (預期 {expected} {tolerance})")
        if detail:
            print(f"         {detail}")
        return passed

    def csv(self, path, fields, rows):
        """排隊一份 CSV。注意：這裡不寫檔。"""
        self.pending.append((path, fields, rows))

    def finalize(self):
        n_fail = sum(1 for c in self.checks if not c[1])

        os.makedirs(DATA, exist_ok=True)

        if n_fail:
            print(f"\n{self.name}: {n_fail}/{len(self.checks)} 個 gate 失敗。"
                  f"**不寫出任何 artifact。**")
            print("半綠的資料比沒有資料更危險——紅燈下產生的 CSV 遲早會被誤用。")
            sys.exit(2)

        # gates.csv：以 (milestone, gate) 為鍵**取代**，不是無腦附加。
        #
        # 第一版是 append（註解寫「保留歷史」）。但那不是歷史——列裡沒有時間戳，
        # 分不出哪一列來自哪一次 run，只是**重複**。實際後果：m5_gate.py 跑了 6 次，
        # gates.csv 就有 6 份一模一樣的 M5 gate；M2 有 3 份。
        # 而 gates.csv 是報告數字的**單一事實來源**，裡面有陳舊的重複列是會出事的。
        #
        # 取代之後這個檔就是冪等的：跑幾次都一樣，也符合「刪掉 data/ 重生會得到相同檔案」
        # 這條可重生性要求。真正的歷史在 git 裡。
        gpath = os.path.join(DATA, "gates.csv")
        old = []
        if os.path.exists(gpath):
            with open(gpath, newline="") as f:
                old = list(csv.DictReader(f))

        new = [{
            "gate": label, "passed": passed, "measured": measured,
            "expected": expected, "tolerance": tol, "detail": detail,
            "milestone": self.milestone,
        } for label, passed, measured, expected, tol, detail in self.checks]

        keys = {(r["milestone"], r["gate"]) for r in new}
        merged = [r for r in old if (r["milestone"], r["gate"]) not in keys] + new

        # 依 milestone 穩定排序，讓 gates.csv 的列序是**確定的**（M0..M5），與 gate 的執行順序無關。
        # 否則單獨重跑某個里程碑的 gate 會用 replace-by-key 把它的列搬到檔尾，讓列序漂移；
        # 完整冷跑（m0->m5 依序）本來就產生 M0..M5 的順序，這個排序讓「單獨重跑」也收斂到同一序，
        # 於是 gates.csv 對「刪光重生」逐位元組可重生（冷跑對 gates.csv 用的是嚴格判準）。
        # 穩定排序保留同一 milestone 內的 check() 呼叫順序。
        milestone_order = {f"M{i}": i for i in range(10)}
        merged.sort(key=lambda r: milestone_order.get(r["milestone"], 99))

        with open(gpath, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=GATES_FIELDS)
            w.writeheader()
            w.writerows(merged)

        for path, fields, rows in self.pending:
            full = os.path.join(DATA, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(rows)

        mpath = os.path.join(DATA, f"meta_{self.name}.json")
        with open(mpath, "w") as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)

        print(f"\n{self.name}: {len(self.checks)}/{len(self.checks)} 個 gate 全綠。")
        print(f"  -> data/gates.csv（取代 {len(self.checks)} 列，冪等）")
        for path, _, rows in self.pending:
            print(f"  -> data/{path}（{len(rows)} 列）")
        print(f"  -> data/meta_{self.name}.json")
        return 0
