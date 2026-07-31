"""check_commsim.py — 既有通訊模擬器（commsim）的定位與內容鎖定。

## 為什麼需要它

`golden/ref_float.py` 與 `tests/test_golden.py` 先前各自寫死一個路徑：

    /mnt/c/Users/fartw/OneDrive/Desktop/github/communications relay simulator

這個相依不是可有可無的裝飾品。commsim 提供：

* `channel.awgn` —— **M1/M2 每一個 BER 點的雜訊都由它產生**
* `modulation` —— BPSK 映射
* `theory` —— G1 的 Q 函數 oracle（未編碼 BPSK 的閉式解）
* `metrics` —— 每個 BER 的 cluster-robust 信賴區間

也就是說：**沒有它，M1 與 M2 一個數字都重生不出來**。而它先前
不在 `requirements.txt`、沒有版本記錄、路徑寫死在某個人的 Windows 桌面下。
任何其他人 clone 這個 repo 都無法重現通訊層的結果，而且不會得到有用的錯誤訊息
——只會是一個 `ModuleNotFoundError`。

## 為什麼是 lock 而不是 vendor

把 commsim 複製進本 repo 會毀掉它的價值。G1 的意義是
「**獨立實作**的 Q 函數與我們的 BER 對得上」；一旦 vendor 進來、跟著本專案一起改，
它就不再獨立，G1 也就不再是交叉驗證。

所以做法是**鎖定而不複製**：記下 remote、commit 與每個被用到的模組的 SHA-256。
內容變了會被抓到，但它仍然是外部的、獨立演進的東西。
"""

import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(REPO, "third_party", "commsim.lock")

# 本專案實際 import 的模組。只鎖這些 —— commsim 有 polar/relay/crc 等
# 與本專案無關的部分，它們改動不該讓這道檢查紅燈。
USED = ["__init__.py", "channel.py", "modulation.py", "theory.py",
        "metrics.py", "bits.py", "coding.py"]

# 候選路徑，依序尋找。第一個是 repo 內的（給 CI / 其他人 clone 之後放置用），
# 其餘是開發機上的已知位置。COMMSIM_PATH 覆寫全部。
CANDIDATES = [
    os.path.join(REPO, "third_party", "commsim-src"),
    "/mnt/c/Users/fartw/OneDrive/Desktop/github/communications relay simulator",
    os.path.expanduser("~/communications-relay-simulator"),
]


def locate():
    """找到 commsim 的根目錄。找不到時回傳 None（由呼叫端決定要不要致命）。

    `COMMSIM_PATH` 一旦設了就是**權威的**：設了但那裡沒有 commsim，就回 None，
    不會偷偷回退到候選路徑。回退會讓「我明明指到 A，它卻用了 B」變成可能，
    而這個相依決定 M1/M2 的每一個 BER 數字 —— 用錯來源比找不到更糟。
    這也讓「commsim 不可得」這條路徑在本機測得起來（CI 上它本來就不可得）。
    """
    env = os.environ.get("COMMSIM_PATH")
    if env:
        return env if os.path.isdir(os.path.join(env, "commsim")) else None
    for c in CANDIDATES:
        if os.path.isdir(os.path.join(c, "commsim")):
            return c
    return None


def digest(root):
    """回傳 {模組: sha256}，外加 git 資訊（若它是 git repo）。"""
    out = {"modules": {}}
    for m in USED:
        p = os.path.join(root, "commsim", m)
        if not os.path.exists(p):
            out["modules"][m] = "absent"
            continue
        with open(p, "rb") as f:
            out["modules"][m] = hashlib.sha256(f.read()).hexdigest()

    def git(*a):
        try:
            return subprocess.check_output(["git", "-C", root, *a],
                                           stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            return "unknown"

    out["git_commit"] = git("rev-parse", "HEAD")
    out["git_remote"] = git("config", "--get", "remote.origin.url")
    return out


def main():
    write = "--write" in sys.argv
    root = locate()
    if root is None:
        print("**找不到 commsim。** M1/M2 的每一個 BER 點都由它產生雜訊，"
              "沒有它就一個數字都重生不出來。")
        print("  設 COMMSIM_PATH，或把它 clone 到 third_party/commsim-src：")
        print("    git clone git@github.com:far9100/communications-relay-simulator.git \\")
        print("      third_party/commsim-src")
        return 1

    cur = digest(root)
    print(f"commsim: {root}")
    print(f"  commit {cur['git_commit'][:12]}  remote {cur['git_remote']}")

    if write:
        os.makedirs(os.path.dirname(LOCK), exist_ok=True)
        with open(LOCK, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        print(f"  -> 已寫入 {os.path.relpath(LOCK, REPO)}")
        return 0

    if not os.path.exists(LOCK):
        print(f"**{os.path.relpath(LOCK, REPO)} 不存在。** 先跑一次 --write。")
        return 1

    with open(LOCK, encoding="utf-8") as f:
        want = json.load(f)

    bad = [m for m in USED if cur["modules"].get(m) != want["modules"].get(m)]
    if bad:
        print("**commsim 的內容與 lock 不符**：" + ", ".join(bad))
        print("  M1/M2 的 BER 由這些模組產生 —— 內容變了，已發表的數字就不再可重現。")
        print("  確認變更是刻意的之後，跑 `python scripts/check_commsim.py --write`，")
        print("  並在 CHANGELOG 記錄為什麼。")
        return 1

    if cur["git_commit"] != want.get("git_commit"):
        # 內容相同但 commit 不同（例如 rebase）：警告但不擋，因為判準是內容。
        print(f"  註：commit 與 lock 不同（lock {want.get('git_commit', '?')[:12]}），"
              f"但被用到的模組內容逐位元組相同。")

    print(f"  OK：{len(USED)} 個模組的 SHA-256 與 lock 相符。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
