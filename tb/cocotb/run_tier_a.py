"""run_tier_a.py — Tier A 的驅動。

RTL 的參數是 elaboration 期決定的，所以每組 (Q, W, D) 都要重建一次 DUT。
把 M1 凍結的向量依 (Q, W, D) 分組，一組建一次、跑一次。
每組通過就落一個 marker，被砍掉可以續跑（Verilator 一次 build 要 20-30 秒，
32 組會超過 harness 的 10 分鐘上限）。

三種模式：

  MODE=c2      安全格點：C2 必須零 mismatch，且 G6 的 assertion **不得**觸發
  MODE=g6neg   不安全格點：C2 **仍然**要零 mismatch（RTL 與 golden 會「錯得一模一樣」，
               這本身就是 C2 有效性的強力佐證），但 G6 的 assertion **必須**觸發
  MODE=g7      用 Icarus 重跑一組，做 4-state 交叉檢查

**G7 為什麼非有不可**：Verilator 是 2-state 的，未初始化的暫存器讀出來是 0 而不是 X。
一個 reset 不完整的 bug 在 Verilator 上會「剛好」是 0 而通過，在真實硬體與 Icarus 上是 X。
只有 4-state 的模擬器叫得出來。
"""

import json
import os
import re
import subprocess
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

NINFO = 256          # M1 凍結向量的 frame 長度
MARKS = os.path.join(REPO, "tb", "cocotb", "build", "_passed")


def groups(safe):
    with open(os.path.join(REPO, "vectors", "MANIFEST.json")) as f:
        vecs = json.load(f)["vectors"]
    g = defaultdict(list)
    for v in vecs:
        if v["safe"] != safe:
            continue
        g[(v["Q"], v["W"], v["D"])].append(v["name"])
    return dict(g)


def run_one(sim, Q, W, D, vec_names, workdir, assertions=True):
    """建置 + 跑一組。回傳 (通過?, **含模擬器在內**的完整輸出)。

    一定要用 subprocess + capture_output：cocotb 的 runner 把模擬器當子行程啟動，
    它的 stdout 直接繼承檔案描述子，Python 層的 redirect_stdout **抓不到**。
    抓不到的後果是 G6 的 assertion 有沒有響，我們根本看不見。

    assertions=False 時不傳 --assert，Verilator 會忽略 immediate assertion。
    這樣才能在不安全格點上把 C2 跑完（否則 assertion 一響就中止，C2 沒跑完）。
    """
    env = dict(os.environ)
    env.update({
        "FEC_REPO": REPO,
        "FEC_SIM": sim,
        "FEC_Q": str(Q), "FEC_W": str(W), "FEC_D": str(D),
        "FEC_NINFO": str(NINFO),
        "FEC_VECTORS": ",".join(vec_names),
        "FEC_WORKDIR": workdir,
        "FEC_ASSERT": "1" if assertions else "0",
        "PYTHONPATH": REPO,
    })
    p = subprocess.run(
        [sys.executable, os.path.join(REPO, "tb", "cocotb", "_run_group.py")],
        capture_output=True, text=True, env=env, cwd=REPO,
    )
    return p.returncode == 0, p.stdout + p.stderr


def main():
    mode = os.environ.get("MODE", "c2")
    sim = "icarus" if mode == "g7" else os.environ.get("SIM", "verilator")
    os.makedirs(MARKS, exist_ok=True)

    if mode == "g7":
        # 用 Icarus 跑一組有代表性的（4-state），證明 reset 是完整的
        g = {k: v for k, v in groups(safe=True).items() if k == (4, 10, 32)}
    elif mode == "g6neg":
        g = groups(safe=False)
    else:
        g = groups(safe=True)

    print(f"=== Tier A  MODE={mode}  SIM={sim}  ({len(g)} 組)")
    sys.stdout.flush()

    total_frames = total_stages = 0
    n_done = 0
    for (Q, W, D), names in sorted(g.items()):
        tag = f"{mode}_{sim}_Q{Q}_W{W}_D{D}"
        mark = os.path.join(MARKS, tag)
        if os.path.exists(mark):
            with open(mark) as f:
                fr, st = (int(x) for x in f.read().split())
            total_frames += fr
            total_stages += st
            n_done += 1
            continue

        wd = os.path.join(REPO, "tb", "cocotb", "build", tag)

        if mode == "g6neg":
            # 兩趟。
            #   趟 1（開 assert）：G6 **必須**響。assertion 一響模擬就中止，所以 C2 跑不完。
            #   趟 2（關 assert）：C2 **仍然**要零 mismatch —— RTL 與 golden 會「錯得一模一樣」。
            #     這一點本身就是 C2 有效性的強力佐證：連在壞掉的字寬下，
            #     兩邊的每一個 bit 都還是相同的。
            _, out1 = run_one(sim, Q, W, D, names, wd + "_a", assertions=True)
            fired = "G6 violated" in out1
            m = re.search(r"G6 violated @ stage (\d+):.*?PM spread=(\d+), 2\^\(W-1\)=(\d+)",
                          out1)
            ev = (f"stage {m.group(1)}, spread {m.group(2)} > 2^(W-1)={m.group(3)}"
                  if m else "?")

            passed, out2 = run_one(sim, Q, W, D, names, wd + "_b", assertions=False)
            stats = re.search(r"C2_STATS (\d+) (\d+) (\d+) (\d+) (\d+)", out2)
            fr = int(stats.group(4)) if stats else 0
            st = int(stats.group(5)) if stats else 0

            ok = fired and passed and fr > 0
            why = (f"G6 觸發（{ev}）+ C2 零 mismatch" if ok else
                   f"G6={'觸發' if fired else '**沒觸發**'}, "
                   f"C2={'通過' if passed else '失敗'}")
        else:
            passed, out = run_one(sim, Q, W, D, names, wd, assertions=True)
            fired = "G6 violated" in out
            stats = re.search(r"C2_STATS (\d+) (\d+) (\d+) (\d+) (\d+)", out)
            fr = int(stats.group(4)) if stats else 0
            st = int(stats.group(5)) if stats else 0
            out2 = out

            ok = passed and not fired and fr > 0
            why = ("C2 零 mismatch，G6 未誤觸發" if ok else
                   f"C2={'通過' if passed else '失敗'}, "
                   f"G6={'**誤觸發**' if fired else '正常'}")

        print(f"  Q={Q} W={W:2d} D={D:2d}  {'PASS' if ok else 'FAIL'}  "
              f"({fr} frames / {st} stages)  {why}")
        sys.stdout.flush()

        if not ok:
            tail = "\n".join(out2.splitlines()[-30:])
            print(f"\n--- 模擬器輸出（末 30 行）---\n{tail}")
            return 1

        with open(mark, "w") as f:
            f.write(f"{fr} {st}")
        total_frames += fr
        total_stages += st
        n_done += 1

    print(f"\nMODE={mode}：{n_done}/{len(g)} 組全部通過")
    print(f"C2_TOTAL {mode} {sim} {n_done} {total_frames} {total_stages}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
