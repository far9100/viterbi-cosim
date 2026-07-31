"""test_design_single_source.py — 防止設計組態與 RTL 清單再度分岔。

`scripts/design.py` 是 winner 組態與 RTL 模組清單的單一來源。但 repo 裡還有
**兩支 shell script**（`check_rtl.sh`、`g7_icarus.sh`）沒辦法 import Python，
它們自己列了一份模組清單。把 shell 改成去問 Python 會讓那兩支腳本多一層相依，
而它們的價值之一正是「不依賴 .venv 也跑得起來」。

所以採取的做法是：**允許 shell 自己列，但用測試釘住它與 design.py 一致**。
加一個模組時，若忘了改 shell，這裡會失敗；而不是等到某次合成少一個檔案、
Yosys 報 hierarchy 錯誤才發現（那還算幸運的——更糟的是它剛好還能合成）。

同時檢查已被單一來源化的 Python 消費端沒有偷偷寫回字面值。
"""

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scripts.design as DESIGN  # noqa: E402

SHELL_WITH_MODULE_LIST = [
    "scripts/check_rtl.sh",
    "scripts/g7_icarus.sh",
]

PY_CONSUMERS = [
    "ppa/synth.py", "ppa/sta.py", "ppa/run_power.py",
    "scripts/tier_b.py", "scripts/m9_sweep.py", "tb/cocotb/_run_group.py",
]


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("rel", SHELL_WITH_MODULE_LIST)
def test_shell_module_list_matches_design(rel):
    """shell 腳本列的 7 個模組必須與 design.MODULES 完全一致（含順序）。"""
    txt = _read(rel)
    found = re.findall(r"\b([a-z_]+\.sv)\b", txt)
    # 去重但保留順序；排除 testbench 自己的檔案
    seen, mods = set(), []
    for m in found:
        if m in seen or m.startswith("tb_") or m.startswith("viterbi_dbg"):
            continue
        seen.add(m)
        mods.append(m)
    assert mods == DESIGN.MODULES, (
        f"{rel} 的模組清單與 scripts/design.py 不一致：\n"
        f"  shell  {mods}\n  design {DESIGN.MODULES}")


@pytest.mark.parametrize("rel", PY_CONSUMERS)
def test_python_consumers_have_no_literal_winner_list(rel):
    """Python 消費端不得再寫死 winner 組態。

    比對的是 `(6, 12, 64)` 這種**四組態同時出現**的樣式 —— 單獨一個 (4, 10, 64)
    可能是別的意思（例如收斂點），所以只在四組都出現時才判為重複的清單。
    """
    txt = _read(rel)
    tuples = set(re.findall(r"\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*[,)]", txt))
    winners = {(str(q), str(w), str(d)) for q, w, d, _c in DESIGN.WINNERS.values()}
    overlap = tuples & winners
    assert len(overlap) < 4, (
        f"{rel} 裡同時出現了全部 4 組 winner 的字面值 {sorted(overlap)} —— "
        f"應改為 import scripts.design")


def test_orders_are_permutations_of_the_same_set():
    """兩種順序必須是同一個集合的排列 —— 不是兩份不同的清單。

    這是單一來源真正要保證的東西：順序可以不同（CSV 列序依賴它），
    但**內容不能不同**。先前五份字面值就是靠人維持一致的。
    """
    assert sorted(DESIGN.ORDER_SYNTH) == sorted(DESIGN.ORDER_POWER)
    assert set(DESIGN.ORDER_SYNTH) == set(DESIGN.WINNERS)


def test_winners_match_m2_selection():
    """winner 必須就是 M2 掃描選出來的那四組（data/m2_winners.csv）。"""
    import csv
    path = os.path.join(ROOT, "data", "m2_winners.csv")
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    from_csv = {(int(r["Q"]), int(r["W"]), int(r["D"]), float(r["clip"]))
                for r in rows}
    assert from_csv == set(DESIGN.WINNERS.values()), (
        f"design.py 的 winner 與 data/m2_winners.csv 不符：\n"
        f"  csv    {sorted(from_csv)}\n"
        f"  design {sorted(DESIGN.WINNERS.values())}")
