"""test_meta_schema.py — 釘住已提交的 `data/meta_*.json` 真的帶著 §5.3 要求的欄位。

為什麼需要這支測試：**metadata 在本專案裡一直是只寫不讀的。**
`scripts/gates.py` 的 `collect_metadata()` 是唯一的寫入端，而讀它的東西一個都沒有——
`check_paper_numbers.py` 完全不碰 meta，`scripts/repro.sh` 更是刻意把 `meta_*.json`
排除在逐位元組比對之外（時間戳每次都會變，不排除的話冷跑永遠不可能相同）。
一個沒有任何讀者的檔案，腐化的時候不會有任何人叫。

而它確實腐化過：M13（`2026-08-01-09`）依 CLAUDE.md §5.3 把 `git_commit_golden` /
`git_commit_rtl` / `git_commit_rtl_lowpower` 與整組環境版本加進 `collect_metadata()`，
並把恆為 true 的 `git_dirty` 改名為只看源碼路徑的 `git_dirty_src`。**但那七份已提交的
證據檔從來沒有重新產生過**，於是「metadata 補完 §5.3」這句話只對程式碼成立、對樹裡的
產物不成立，一直到 2026-08-08 跑 `make gates` 才被看見。

§5.3 存在的理由是「一個無法追溯到 (seed, 組態, commits) 的 BER 點不是證據」。
帶著舊 schema 的 meta 恰恰做不到這件事：沒有 golden / rtl 各自的 commit，
就無法佐證 C2 所依賴的「兩份實作互相獨立」；而恆為 true 的 dirty 旗標等於沒有旗標。

所以這裡釘三件事，對應三種不同的腐化方式：
  1. 每一份 meta 都帶齊 §5.3 的可追溯性欄位（抓「schema 改了但產物沒重生」）。
  2. 七份的鍵集必須一致（抓「只重跑了部分里程碑」造成的半新半舊）。
  3. 寫入端 `md = {...}` 字面值裡的每一個鍵，都必須出現在已提交的產物裡
     （抓「未來又加了欄位卻忘記重生」——這正是 M13 踩到的那一種）。
"""

import ast
import datetime
import glob
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_FILES = sorted(glob.glob(os.path.join(ROOT, "data", "meta_*.json")))

# CLAUDE.md §5.3 逐條列舉的可追溯性欄位。
# 前四項是「哪一次 run」，中間四項是「哪一份源碼」，其餘是「什麼環境」。
# `cupy` 本專案用 torch 取代，故記 torch + cuda；PDK / 合成工具版本住在 ORFS
# 容器裡，由 eda_versions 與 orfs_image 兩欄承接。
REQUIRED_53 = [
    "start_timestamp", "argv", "run", "milestone",
    "git_commit", "git_dirty_src",
    "git_commit_golden", "git_commit_rtl", "git_commit_rtl_lowpower",
    "python", "numpy", "cocotb", "torch", "cuda",
    "verilator", "iverilog",
    "eda_versions", "orfs_image",
]

# M13 之前的欄位名。它若還在，代表這份產物早於 M13 而且沒有重生過。
LEGACY_KEYS = ["git_dirty"]

COMMIT_KEYS = ["git_commit", "git_commit_golden", "git_commit_rtl",
               "git_commit_rtl_lowpower"]

_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_meta_files_exist():
    """七個里程碑各有一份 meta。少一份代表某條量測鏈路沒有留下可追溯性紀錄。"""
    assert len(META_FILES) == 7, [os.path.basename(p) for p in META_FILES]


@pytest.mark.parametrize("path", META_FILES, ids=lambda p: os.path.basename(p))
def test_required_53_keys_present(path):
    """§5.3 的每一個欄位都必須在檔案裡。這是 M13 那次腐化會被抓到的地方。"""
    md = _load(path)
    missing = [k for k in REQUIRED_53 if k not in md]
    assert missing == [], f"{os.path.basename(path)} 缺少 §5.3 欄位: {missing}"


@pytest.mark.parametrize("path", META_FILES, ids=lambda p: os.path.basename(p))
def test_legacy_keys_absent(path):
    """舊欄位名不得殘留——它的存在本身就是「這份產物沒有重生過」的證據。"""
    md = _load(path)
    stale = [k for k in LEGACY_KEYS if k in md]
    assert stale == [], f"{os.path.basename(path)} 仍帶著 M13 之前的欄位: {stale}"


@pytest.mark.parametrize("path", META_FILES, ids=lambda p: os.path.basename(p))
def test_traceability_values_are_usable(path):
    """欄位在不代表值可用。一個空字串的 commit hash 追溯不到任何東西。"""
    md = _load(path)
    name = os.path.basename(path)

    for k in COMMIT_KEYS:
        assert _HEX40.match(str(md[k])), f"{name} 的 {k} 不是 40 位十六進位: {md[k]!r}"

    # 恆為 true 的旗標等於沒有旗標，所以型別必須是 bool 而不是字串
    assert isinstance(md["git_dirty_src"], bool), f"{name} 的 git_dirty_src 不是 bool"

    assert isinstance(md["argv"], list) and md["argv"], f"{name} 的 argv 是空的"
    datetime.datetime.strptime(md["start_timestamp"], "%Y-%m-%dT%H:%M:%S%z")

    for k in ("run", "milestone", "python"):
        assert str(md[k]).strip(), f"{name} 的 {k} 是空的"


def test_all_meta_share_one_key_set():
    """七份的鍵集必須完全一致。

    只重跑部分里程碑時，樹裡會同時存在新舊兩種 schema，而 `gates.py` 的
    finalize() 是以里程碑為單位整批取代的——沒被跑到的那幾份會靜靜地留在舊版本。
    """
    sets = {os.path.basename(p): set(_load(p)) for p in META_FILES}
    common = set.intersection(*sets.values())
    odd = {n: sorted(s ^ common) for n, s in sets.items() if s != common}
    assert odd == {}, f"鍵集不一致: {odd}"


def test_writer_literal_keys_all_landed_in_artifacts():
    """`collect_metadata()` 的 `md = {...}` 字面值裡的鍵，產物裡必須一個不少。

    這是三道檢查裡唯一會**自動**跟上未來改動的一道：往那個字面值加欄位卻沒有
    重新產生 meta，這裡就會紅燈。M13 加的四個欄位正是加在那個字面值裡。

    只解析字面值、不呼叫 `collect_metadata()`：後者會 docker run 進 ORFS 容器問
    工具版本（120 秒 timeout）、跑 verilator 與 iverilog，那不是單元測試該做的事。
    迴圈產生的欄位（numpy / cocotb / torch / cuda / verilator / iverilog 等）
    由上面的 REQUIRED_53 涵蓋。
    """
    src = open(os.path.join(ROOT, "scripts", "gates.py"), encoding="utf-8").read()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "collect_metadata")

    literal_keys = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for k in node.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    literal_keys.add(k.value)
    assert literal_keys, "解析不到 collect_metadata() 的 md 字面值——寫入端結構變了"

    for path in META_FILES:
        missing = sorted(literal_keys - set(_load(path)))
        assert missing == [], (
            f"{os.path.basename(path)} 缺少寫入端已經有的欄位 {missing}；"
            "改了 collect_metadata() 就要重新產生 meta（make gates）")
