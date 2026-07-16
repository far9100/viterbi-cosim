"""run_power.py — gate-level 功耗掃描（分區塊 × SNR）。可續跑。

每個點約 2–4 分鐘（Icarus 跑 34k 個 cell 的 gate-level，約 12 cycles/s），
harness 有 10 分鐘上限，所以每個點做完就落快取，被砍掉不用重跑。
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ppa.power as P  # noqa: E402
from scripts.gates import DATA, REPO  # noqa: E402

CACHE = os.path.join(DATA, "cache_m5")

# depth=4 是實測出來的：depth 2 -> 0.01%、3 -> 81.95%、4 -> **100.00%** 的 annotation。
# 太淺會漏掉 netlist 的 net（OpenSTA 會靜靜地套用預設猜測）；
# 太深會 dump 到 cell 內部（OpenSTA 根本不需要，只是拖慢模擬）。
DUMP_DEPTH = 4

# 每點的 frame 數。收斂性由 convergence 那一段實測證明，不是假設。
FRAMES = 3

SNR_SWEEP = [1.0, 2.0, 3.0, 4.0, 5.0]
CONFIGS = [
    # (Q, W, D, clip, [SNRs])
    (4, 10, 64, 2.5, SNR_SWEEP),      # 主掃描：功耗 vs SNR（交付結果）
    (6, 12, 64, 3.0, [3.0]),
    (6, 12, 32, 3.0, [3.0]),
    (3,  8, 32, 2.0, [3.0]),
]


def point(Q, W, D, clip, snr, frames=FRAMES):
    tag = f"Q{Q}_W{W}_D{D}"
    key = f"{tag}_snr{snr}_f{frames}"
    cp = os.path.join(CACHE, f"{key}.json")
    if os.path.exists(cp):
        with open(cp) as f:
            return json.load(f)

    netlist = os.path.join(REPO, "ppa", "out", "synth", f"net_{tag}.v")
    vvp, n_cells = P.build_gl(tag, netlist, Q, W, D, P.NINFO)

    sd = os.path.join(P.OUT, f"stim_{tag}_{snr}")
    sp, dp, T = P.make_stimulus(Q, W, D, clip, snr, sd)

    t0 = time.time()
    saif, ok, n_nets, dt_sim, simout = P.run_saif(tag, vvp, sp, dp, T, snr,
                                                  frames=frames, depth=DUMP_DEPTH)
    if not ok:
        raise RuntimeError(f"gate-level C2 失敗 ({key}):\n{simout[-1200:]}")

    sta = P.run_sta(tag, netlist, saif, snr)
    pr = P.parse_power(sta)

    row = {"tag": tag, "Q": Q, "W": W, "D": D, "clip": clip, "snr_db": snr,
           "frames": frames, "n_stages": frames * T,
           "annot_pct": pr.get("annot_pct", 0.0),
           "n_nets": n_nets, "saif_mb": round(os.path.getsize(saif) / 1e6, 1),
           "sim_s": round(dt_sim, 1), "wall_s": round(time.time() - t0, 1)}
    for k in ["total"] + P.BLOCKS:
        v = pr.get(k)
        if v:
            row[f"p_{k}_w"] = v["total"]
            row[f"p_{k}_int_w"] = v["internal"]
            row[f"p_{k}_sw_w"] = v["switching"]
            row[f"p_{k}_leak_w"] = v["leakage"]

    os.makedirs(CACHE, exist_ok=True)
    with open(cp + ".tmp", "w") as f:
        json.dump(row, f)
    os.replace(cp + ".tmp", cp)
    return row


def main():
    os.makedirs(P.OUT, exist_ok=True)
    jobs = [(Q, W, D, clip, s) for (Q, W, D, clip, snrs) in CONFIGS for s in snrs]

    # 收斂性：同一個點跑 1 / 2 / 3 個 frame，證明功耗已經穩定
    conv_jobs = [(4, 10, 64, 2.5, 3.0, f) for f in (1, 2)]

    done = sum(1 for j in jobs
               if os.path.exists(os.path.join(
                   CACHE, f"Q{j[0]}_W{j[1]}_D{j[2]}_snr{j[4]}_f{FRAMES}.json")))
    print(f"=== 功耗掃描：{len(jobs)} 個點（快取 {done}），"
          f"外加 {len(conv_jobs)} 個收斂性點")
    sys.stdout.flush()

    t0 = time.time()
    rows = []
    for Q, W, D, clip, snr in jobs:
        if time.time() - t0 > 460:
            print(f"時間預算用盡，乾淨結束。再跑一次即可續做。")
            return 1
        r = point(Q, W, D, clip, snr)
        rows.append(r)
        tot = r.get("p_total_w", 0)
        print(f"  {r['tag']:14s} snr={snr}  annot={r['annot_pct']:.1f}%  "
              f"P={tot*1e3:7.3f} mW  "
              f"[tb {r.get('p_u_tb_w',0)*1e3:6.3f}  acs {r.get('p_u_acs_w',0)*1e3:6.3f}  "
              f"minpm {r.get('p_u_minpm_w',0)*1e3:6.3f}]  ({r['wall_s']:.0f}s)")
        sys.stdout.flush()

    conv = []
    for Q, W, D, clip, snr, f in conv_jobs:
        # 收斂點也納入可續跑的預算：預算用盡就乾淨結束並回傳 1，讓 until 迴圈續跑。
        # 原本是 break——但 break 之後仍 return 0，會讓某個收斂點（例如 f2）被靜靜丟掉，
        # 而 power.json 少一個點卻仍被當成功。冷跑抓到過這個不確定性（f2 有時在、有時不在）。
        # point() 有快取，續跑時已算過的點瞬間返回，最後一趟全命中才寫出完整、確定的 power.json。
        if time.time() - t0 > 520:
            print("時間預算用盡（收斂點），乾淨結束。再跑一次即可續做。")
            return 1
        conv.append(point(Q, W, D, clip, snr, frames=f))

    # sim_s / wall_s 是 wall-clock 遙測，每次都會變，不是科學結果。它們不入 git 追蹤的證據檔
    # （否則 power.json 永遠無法逐位元組重生）；功耗數值 p_*_w 才是證據。run 層級的計時另有記錄。
    def _no_timing(r):
        return {k: v for k, v in r.items() if k not in ("sim_s", "wall_s")}
    with open(os.path.join(DATA, "power.json"), "w") as f:
        json.dump({"points": [_no_timing(r) for r in rows],
                   "convergence": [_no_timing(r) for r in conv]}, f, indent=2)
    print(f"\n-> data/power.json（{len(rows)} 個點）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
