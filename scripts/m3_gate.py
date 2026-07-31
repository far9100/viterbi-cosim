"""m3_gate.py — M3 的驗收：G5 (C2)、G6（正向 + 負向）、G7、三重前端。

C2 的對外宣稱格式（規格書 DoD §2）：
    「N 個測試向量 × M 個 stage 比對，0 mismatch」
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.gates import REPO, Run  # noqa: E402


def sh(cmd, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(["bash", "-lc", cmd], cwd=REPO, capture_output=True,
                       text=True, env=e, timeout=3600)
    return p.returncode, p.stdout + p.stderr


def main():
    run = Run("m3_rtl", milestone="M3")

    # ---------- 三重前端 ----------
    rc, out = sh("bash scripts/check_rtl.sh")
    run.check("M3-0 三重前端（Verilator / Icarus / Yosys 0.64）", rc == 0,
              measured="三個都通過" if rc == 0 else "有前端失敗",
              expected="全部通過", tolerance="—",
              detail="Yosys 0.64 的 SV 前端最弱，而它是 M5 合成的必經之路。"
                     "第 5 週才發現它吃不下某個構造，就是這種專案掉一週的經典死法。"
                     "所以從第一個 RTL commit 起就跑。")

    # ---------- G5 = C2 ----------
    rc, out = sh("MODE=c2 bash scripts/tier_a.sh")
    m = re.search(r"C2_TOTAL c2 \w+ (\d+) (\d+) (\d+)", out)
    n_grp, n_fr, n_st = (int(m.group(i)) for i in (1, 2, 3)) if m else (0, 0, 0)
    run.check("G5 = C2：L2 ↔ L3 位元級相等", rc == 0 and n_st > 0,
              measured=f"{n_grp} 組 (Q,W,D) / {n_fr} frames / {n_st} stages，0 mismatch",
              expected="零 mismatch", tolerance="零容忍",
              detail="每個 stage 比對 bm[4] / pm[64] / survivor[64] / **解碼位元**，"
                     "並在 stage_done 的脈衝上觸發（不是靠數 cycle）。"
                     "解碼位元必須納入比對集：traceback 策略不同會改 BER，"
                     "卻能完整通過只比 bm/pm/survivor 的 C2——這個 bug 在 M3 真的發生過。")

    # ---------- G6：安全格點不得誤觸發（已含在 C2 那一輪）----------
    run.check("G6 正向：安全格點不得誤觸發", rc == 0 and n_grp > 0,
              measured=f"{n_grp} 組安全格點，assertion 全程未響",
              expected="不觸發", tolerance="零容忍",
              detail="G6 的定義是**決策等價**：RTL 的 modulo survivor 必須等於"
                     "無界參考算術導出的 survivor。RTL 內以 always_ff 的 immediate "
                     "assertion 實作（不用 bind、不用 concurrent SVA —— Icarus 不支援）。")

    # ---------- G6 負向 ----------
    rc6, out6 = sh("MODE=g6neg bash scripts/tier_a.sh")
    fires = re.findall(r"G6 觸發（stage (\d+), spread (\d+) > 2\^\(W-1\)=(\d+)）", out6)
    m6 = re.search(r"C2_TOTAL g6neg \w+ (\d+) (\d+) (\d+)", out6)
    n6 = int(m6.group(1)) if m6 else 0
    ev = "; ".join(f"stage {a}, spread {b}>{c}" for a, b, c in fires)
    run.check("G6 負向：4 個先驗不安全格點必須觸發", rc6 == 0 and len(fires) == 4,
              measured=f"{len(fires)}/4 觸發 —— {ev}",
              expected="4/4 觸發", tolerance="零容忍",
              detail="不必人工把 W 調到 6（規格書 v1 的做法）——既有網格裡本來就有 4 個"
                     "先驗不安全的格點。而且這些格點上 **C2 仍然零 mismatch**："
                     "RTL 與 golden 錯得一模一樣，這本身就是 C2 有效性的強力佐證。")

    # ---------- M3-2 rtl_lowpower 的 C2 ----------
    #
    # `rtl_lowpower/` 是 M9 的 B0'/B1' 所合成的原始碼，也就是 -42.7% 功耗與
    # -11.02% 面積這些**已發表數字的來源**。它先前不被 lint、不進 Tier A、不進 Tier B，
    # 唯一的檢查是閘級的 verify_cg —— 而那道檢查在 M10 之前還驗錯了 netlist。
    # 「兩份 RTL 語意等價」先前只是一句註解；這裡把它變成零容忍的比對。
    rcl, outl = sh("MODE=c2lp bash scripts/tier_a.sh")
    ml = re.search(r"C2_TOTAL c2lp \w+ \d+ (\d+) (\d+)", outl)
    lp_f = int(ml.group(1)) if ml else 0
    lp_s = int(ml.group(2)) if ml else 0
    run.check("M3-2 rtl_lowpower 的 C2（RTL 層）", rcl == 0 and lp_s > 0,
              measured=f"{lp_f} frames / {lp_s} stages，0 mismatch",
              expected="零 mismatch", tolerance="零容忍",
              detail="與 rtl/ 同一組凍結向量、同一個 golden model 比對 "
                     "bm/pm/survivor/解碼位元。這是 rtl_lowpower/ 第一次在 RTL 層被驗證；"
                     "docs/lowpower_baseline.md §4.1 要求「先過 C2 才准量功耗」，"
                     "先前只有閘級那一半（ppa/verify_cg.py），RTL 層是空的。")

    # ---------- M3-1 控制路徑 ----------
    #
    # C2 把資料路徑驗到 2.47 億個 stage 零 mismatch，但**所有**的 testbench 都用
    # 同一種方式驅動 DUT：in_valid 連續拉高、只在 frame 開頭 reset、frame 之間必 reset。
    # 於是 stall、frame_done、幀中 reset、背靠背 frame 四件事從來沒有被激勵過。
    # 其中 frame_done 更是 grep 全 repo 沒有任何測試讀過 —— 它可以恆為 0，
    # 而先前所有 gate 都還是綠的。
    rcc, outc = sh("MODE=ctrl bash scripts/tier_a.sh")
    # CTRL_STATS 是印在 cocotb 子行程的 stdout 裡的，run_tier_a 不會轉印；
    # 但它已經被聚合進 run_tier_a 自己印的 C2_TOTAL 那一行（frames 欄 = 通過的條數、
    # stages 欄 = stall 空拍數）。抓聚合行，不抓子行程的行。
    mc = re.search(r"C2_TOTAL ctrl \w+ \d+ (\d+) (\d+)", outc)
    n_ctrl = int(mc.group(1)) if mc else 0
    n_stall = int(mc.group(2)) if mc else 0
    run.check("M3-1 控制路徑（stall / frame_done / 幀中 reset / 背靠背）",
              rcc == 0 and n_ctrl == 4,
              measured=f"{n_ctrl}/4 條通過（{n_stall} 個 stall 空拍）",
              expected="4/4 通過", tolerance="零容忍",
              detail="四條：(a) frame 中途拉低 in_valid，解碼位元必須與無 stall 時"
                     "**逐位元相同**——stage_en 同時 gate 住三個模組的四組暫存器"
                     "（pm / surv_r / re / bm_r），任何一組錯拍都會在這裡出現；"
                     "(b) frame_done 必須恰好拉高一次（先前沒有任何測試讀過它）；"
                     "(c) frame 中途 reset 後重灌一整幀，結果必須與基準相同"
                     "——這正是 rtl_lowpower/ 的 reset-in-enable 改寫要保護的東西；"
                     "(d) 不 reset 的背靠背 frame 必須無輸出，"
                     "這是 ctrl.sv 停在 S_DONE 的**設計限制**，把它釘住以免"
                     "行為改變而沒有人更新 report §5 的限制清單。")

    # ---------- G7 ----------
    rc7, out7 = sh("bash scripts/g7_icarus.sh")
    passes = re.findall(r"TB_RESULT PASS (\d+) (\d+)", out7)
    n_f7 = sum(int(a) for a, _ in passes)
    n_b7 = sum(int(b) for _, b in passes)
    run.check("G7：Icarus（4-state）交叉檢查", rc7 == 0 and len(passes) >= 6,
              measured=f"{len(passes)} 個向量 / {n_f7} frames / {n_b7} bits，"
                       f"C2 零 mismatch 且輸出從未出現 X/Z",
              expected="零 X/Z、零 mismatch", tolerance="零容忍",
              detail="Verilator 是 2-state 的：未初始化的暫存器讀為 0 而非 X，"
                     "一個 reset 不完整的 bug 會「剛好」通過。只有 4-state 叫得出來。"
                     "cocotb + Icarus 在本機走不通（oss-cad-suite 自帶的 glibc 太舊，"
                     "撐不起 cocotb VPI 要 dlopen 的系統 libpython），"
                     "所以 Icarus 這一側改用**檔案驅動**的 TB，完全不碰 Python。"
                     "同一支 TB 之後 M5 的 gate-level 模擬也會用到。")

    run.csv("m3_c2.csv",
            ["metric", "value"],
            [{"metric": "c2_groups", "value": n_grp},
             {"metric": "c2_frames", "value": n_fr},
             {"metric": "c2_stages", "value": n_st},
             {"metric": "g6_negative_cells_fired", "value": len(fires)},
             {"metric": "g7_frames", "value": n_f7},
             {"metric": "g7_bits", "value": n_b7}])

    print(f"\n=== C2 的對外宣稱")
    print(f"    {n_grp} 組 (Q,W,D) 組態 × {n_fr} 個 frame × {n_st} 個 stage 比對，"
          f"**0 mismatch**")
    print(f"    每個 stage 比對：bm[4]、pm[64]、survivor[64]、解碼位元")
    print(f"\n=== G6 負向的證據")
    for a, b, c in fires:
        print(f"    stage {a} 觸發，實測 PM spread {b} > 2^(W-1) = {c}")

    return run.finalize()


if __name__ == "__main__":
    sys.exit(main())
