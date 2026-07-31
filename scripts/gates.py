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


def _milestone_key(row):
    """gates.csv 的排序鍵：把 "M12" 解析成 12，讓里程碑編號沒有上限。

    無法解析的 milestone 排到最後（而不是拋例外）——gates.csv 是既有檔案，
    真有一列壞掉時，寧可讓它排在檔尾被看見，也不要讓整支 gate script 掛掉而不寫任何 artifact。
    """
    ms = str(row.get("milestone", ""))
    return (0, int(ms[1:])) if ms[:1] == "M" and ms[1:].isdigit() else (1, 0)



# 「源碼」的定義：會改變數字的東西。`data/` 不在裡面 —— 它是輸出，
# 而冷跑會先把它刪光，把它算進 dirty 只會讓旗標恆為 true。
SRC_PATHS = ["golden", "rtl", "rtl_lowpower", "ppa", "scripts", "sweep",
             "tb", "tests", "docs", "Makefile", "requirements.txt"]


def _eda_versions():
    """PPA 工具鏈的版本。它們住在 ORFS 容器裡，主機上問不到。

    CLAUDE.md §5.3 明列 PPA run 必須記錄 PDK 與合成工具版本。先前一個都沒記 ——
    整條面積 / Fmax / 功耗鏈路的可追溯性因此缺一角：`openroad/orfs` 這個 image
    若換了版本，所有 PPA 數字都會變，而沒有任何一份 metadata 說得出當時用的是哪一版。
    容器起不來時記 "absent"，不讓 metadata 收集失敗把 gate 拖下水。
    """
    out = {}
    try:
        p = subprocess.run(
            ["bash", os.path.join(REPO, "ppa", "orfs.sh"),
             "yosys -V; openroad -version; sta -version"],
            capture_output=True, text=True, timeout=120)
        txt = (p.stdout + p.stderr).strip().splitlines()
        out["eda_versions"] = [ln.strip() for ln in txt if ln.strip()][:6]
    except Exception:
        out["eda_versions"] = "absent"
    # image 的 digest：`:latest` 會浮動，digest 才是真正釘得住的東西
    try:
        p = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}",
             "openroad/orfs:latest"], capture_output=True, text=True, timeout=60)
        out["orfs_image"] = p.stdout.strip() or "absent"
    except Exception:
        out["orfs_image"] = "absent"
    return out


def collect_metadata(extra=None):
    """收集重現這次 run 所需的全部資訊（CLAUDE.md §5.3）。

    為什麼要這麼囉唆：前一個專案吃過虧——有個純量的分析參數沒進 metadata，
    事後完全無法追溯或對帳。一個無法追溯到 (seed, 組態, commit) 的 BER 點不是證據。
    """
    md = {
        "start_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "argv": sys.argv,
        "git_commit": _git("rev-parse", "HEAD"),
        # **只看源碼路徑。**
        #
        # 原本是 `git status --porcelain`（整個工作區），於是七份 meta 全部記
        # `git_dirty: true` —— 而根因是 `repro.sh` 第 2 步 `rm -rf data` 刪掉了
        # git 追蹤中的 `data/`。那不是源碼髒，卻讓「這個 commit 描述了產生這些
        # 數字的程式碼」這句話在每一份 metadata 上都掛著一個假的警示。
        # 警示要嘛精確，要嘛就沒有用；恆為 true 的旗標等於沒有旗標。
        "git_dirty_src": bool(_git("status", "--porcelain", "--",
                                   *SRC_PATHS)),
        # 各子系統各自的 commit（CLAUDE.md §5.3）。C2 的意義建立在
        # 「golden 與 rtl 是兩份獨立實作」，所以要分別可追溯到自己的版本。
        "git_commit_golden": _git("log", "-1", "--format=%H", "--", "golden"),
        "git_commit_rtl": _git("log", "-1", "--format=%H", "--", "rtl"),
        "git_commit_rtl_lowpower": _git("log", "-1", "--format=%H", "--",
                                        "rtl_lowpower"),
        "python": sys.version.split()[0],
    }
    for mod in ("numpy", "cocotb", "matplotlib", "torch"):
        try:
            md[mod] = __import__(mod).__version__
        except Exception:
            md[mod] = "absent"
    # CUDA 只有在 torch 帶得動的時候才有意義
    try:
        import torch
        md["cuda"] = torch.version.cuda or "cpu-only"
        md["gpu"] = (torch.cuda.get_device_name(0)
                     if torch.cuda.is_available() else "absent")
    except Exception:
        md["cuda"] = md["gpu"] = "absent"
    for tool, args in (("verilator", ["--version"]), ("iverilog", ["-V"])):
        try:
            out = subprocess.check_output([tool, *args], stderr=subprocess.STDOUT)
            md[tool] = out.decode().splitlines()[0].strip()
        except Exception:
            md[tool] = "absent"
    md.update(_eda_versions())
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

        # **以 milestone 為單位整批取代，不是以 (milestone, gate) 為鍵逐列取代。**
        #
        # 逐列取代有一個已經咬過一次的破口（見 CHANGELOG `2026-07-16-08`）：
        # gate **改名**之後，舊名字那一列不會被任何新列取代，於是留下孤兒，把總數灌大。
        # 當時是 M2 的 C2′ 改名（…L2-GPU… -> …L2-torch…）把 26 灌成 27；
        # M9 開發期間又發生一次（M9-7 改名後舊列殘留）。**同一個破口咬兩次，就該修根因。**
        #
        # 根因是「一個 run 只擁有自己產生的那幾列」這個假設太弱：本專案每個 milestone
        # 就是一支 script，它產生該 milestone 的**完整集合**。所以正確的語意是
        # 「這個 run 擁有這個 milestone 的全部列」——整批取代之後，
        # 孤兒在結構上不可能存在，不必再靠人去發現。
        merged = [r for r in old if r["milestone"] != self.milestone] + new

        # 依 milestone 穩定排序，讓 gates.csv 的列序是**確定的**（M0..Mn），與 gate 的執行順序無關。
        # 否則單獨重跑某個里程碑的 gate 會用 replace-by-key 把它的列搬到檔尾，讓列序漂移；
        # 完整冷跑（m0->m9 依序）本來就產生 M0..M9 的順序，這個排序讓「單獨重跑」也收斂到同一序，
        # 於是 gates.csv 對「刪光重生」逐位元組可重生（冷跑對 gates.csv 用的是嚴格判準）。
        # 穩定排序保留同一 milestone 內的 check() 呼叫順序。
        #
        # **排序鍵用解析的，不用寫死的表。** 第一版是 `{f"M{i}": i for i in range(10)}`，
        # 上限剛好卡在專案當時的最後一個里程碑 M9。一旦出現 M10，它和之後的每一個里程碑
        # 都會落到同一個 fallback 鍵，穩定排序就退化成「哪一支 gate 最後跑」——
        # 也就是列序重新取決於執行順序，正是這段排序當初要消滅的東西。
        # 而且它不會報錯，只會讓冷跑的逐位元組判準偶發性地紅燈，很難查。
        merged.sort(key=_milestone_key)

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
