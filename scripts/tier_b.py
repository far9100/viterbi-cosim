"""tier_b.py — Tier B 的浸泡驅動。

平行化依規格書 §4：**跨 (組態 × SNR) 開獨立 process**，各 run 完全獨立。
**不要用 Verilator 的 --threads**——對 64-state 這種小設計幫助有限。
**浸泡時絕不開 --trace**（會慢 10-50 倍）。

流程（每個點）：
    1. gen_stimulus.py 產生 stimulus.bin + expected.bits + manifest.json（含 SHA-256）
    2. Verilator 建 C++ harness（一次 build 對應一組 (Q,W,D)）
    3. 跑：重播激勵、解碼位元 XOR、零容忍
    4. 對帳：檔案的 SHA-256 必須與 manifest 相符（CLAUDE.md §5.1(d)）
    5. 刪掉激勵（可由 seed 重生；manifest 入庫，位元組不入庫）
"""

import json
import os
import shutil
import subprocess
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.gates import DATA, REPO  # noqa: E402
from scripts.gen_stimulus import generate, verify  # noqa: E402

NINFO = 1024
SEED = 20260714
WORK = os.path.join(REPO, "ppa", "out", "tierb")
MANIFESTS = os.path.join(DATA, "tierb_manifests")

RTL = ["rtl/bmu.sv", "rtl/acs_butterfly.sv", "rtl/acs_array.sv", "rtl/minpm.sv",
       "rtl/traceback.sv", "rtl/ctrl.sv", "rtl/viterbi_top.sv"]

# M2 選出的 winner（data/m2_winners.csv）
WINNERS = [
    (6, 12, 64, 3.0),
    (6, 12, 32, 3.0),
    (4, 10, 64, 2.5),
    (3,  8, 32, 2.0),
]
# 低 SNR 是 G6 assertion 浸泡的重點：PM spread 在那裡最大。
SNRS = [1.0, 3.0, 5.0]
FRAMES = int(os.environ.get("TIERB_FRAMES", "20000"))   # 每點 ~2x10^7 bits


def build(Q, W, D):
    """建一次 C++ harness。同一組 (Q,W,D) 的所有 SNR 共用。"""
    obj = os.path.join(WORK, f"obj_Q{Q}_W{W}_D{D}")
    exe = os.path.join(obj, "Vviterbi_top")
    if os.path.exists(exe):
        return exe
    os.makedirs(WORK, exist_ok=True)

    cmd = [
        "verilator", "--cc", "--exe", "--build", "-j", "4",
        "--assert",                       # G6 的 immediate assertion 要真的會叫
        "--x-assign", "fast", "--x-initial", "fast",
        "-Wno-fatal",
        "-CFLAGS", "-O2",
        "-Irtl",
        "--top-module", "viterbi_top",
        f"-GQ={Q}", f"-GW={W}", f"-GD={D}", f"-GNINFO={NINFO}",
        "-Mdir", obj,
        *[os.path.join(REPO, f) for f in RTL],
        os.path.join(REPO, "tb", "cpp", "sim_main.cpp"),
    ]
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(exe):
        raise RuntimeError(f"Verilator build 失敗 (Q={Q} W={W} D={D}):\n"
                           f"{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    return exe


def gen_point(args):
    """Phase 1：產生激勵。**序列跑**，只開一個 CUDA context。

    不在平行的 worker 裡各自產生激勵：6 個 process 各開一個 CUDA context
    （每個 ~500 MB）會把 GPU 記憶體吃掉一大塊——而 GPU 目前被別的專案佔著。
    """
    Q, W, D, clip, snr = args
    tag = f"Q{Q}_W{W}_D{D}_snr{snr}"
    outdir = os.path.join(WORK, f"stim_{tag}")
    t0 = time.time()
    m = generate(Q, W, D, clip, snr, FRAMES, NINFO, SEED, outdir, use_gpu=True)
    return args, m, round(time.time() - t0, 1)


def one_point(args):
    """Phase 3：跑模擬。**純 CPU**，跨 (組態 × SNR) 開獨立 process。"""
    (Q, W, D, clip, snr), m, t_gen = args
    tag = f"Q{Q}_W{W}_D{D}_snr{snr}"
    outdir = os.path.join(WORK, f"stim_{tag}")

    exe = build(Q, W, D)
    T = NINFO + 6

    t1 = time.time()
    p = subprocess.run(
        [exe,
         os.path.join(outdir, m["stimulus_file"]),
         os.path.join(outdir, m["expected_file"]),
         str(FRAMES), str(T), str(NINFO), str(D)],
        capture_output=True, text=True, cwd=REPO,
    )
    t_sim = time.time() - t1

    # G6 的 assertion 有沒有在浸泡中響？（安全格點不該響）
    g6_fired = "G6 violated" in (p.stdout + p.stderr)

    res = {}
    for line in p.stdout.splitlines():
        if line.startswith("TIERB_RESULT"):
            for kv in line.split()[1:]:
                k, v = kv.split("=")
                res[k] = int(v)

    # 對帳：檔案的 SHA-256 必須與 manifest 相符
    man_path = os.path.join(outdir, f"manifest_{tag}.json")
    sha_ok, _ = verify(man_path)

    # manifest 入庫（可追溯），激勵位元組不入庫（可由 seed 重生）
    os.makedirs(MANIFESTS, exist_ok=True)
    shutil.copy(man_path, os.path.join(MANIFESTS, f"manifest_{tag}.json"))
    shutil.rmtree(outdir, ignore_errors=True)

    n_stages = FRAMES * T
    ok = (p.returncode == 0 and sha_ok and not g6_fired
          and res.get("mismatches", 1) == 0 and res.get("out_bad", 1) == 0)

    return {
        "tag": tag, "Q": Q, "W": W, "D": D, "clip": clip, "snr_db": snr,
        "n_frames": FRAMES, "n_bits": FRAMES * NINFO, "n_stages": n_stages,
        "mismatches": res.get("mismatches", -1),
        "out_bad": res.get("out_bad", -1),
        "sha256_ok": sha_ok,
        "g6_fired": g6_fired,
        "ok": ok,
        "gen_s": round(t_gen, 1), "sim_s": round(t_sim, 1),
        "sim_khz": round(n_stages / t_sim / 1e3, 1) if t_sim > 0 else 0,
        "stimulus_sha256": m["stimulus_sha256"],
        "expected_sha256": m["expected_sha256"],
    }


def main():
    jobs = [(Q, W, D, clip, s) for (Q, W, D, clip) in WINNERS for s in SNRS]
    print(f"=== Tier B：{len(jobs)} 個點 × {FRAMES:,} frames "
          f"= {len(jobs) * FRAMES * NINFO / 1e6:.0f} M bits 的 C2 浸泡")
    sys.stdout.flush()

    # Phase 1：產生激勵（序列，只開一個 CUDA context）
    t0 = time.time()
    gen = []
    for j in jobs:
        gen.append(gen_point(j))
        print(f"   激勵 {gen[-1][1]['tag']}  {gen[-1][2]}s")
        sys.stdout.flush()
    print(f"   激勵全部產生完成（{time.time()-t0:.0f}s）")

    # Phase 2：build（避免多個 process 同時建同一個 obj dir）
    for Q, W, D, _ in WINNERS:
        build(Q, W, D)
    print("   Verilator build 完成")
    sys.stdout.flush()

    # Phase 3：跨 (組態 × SNR) 開獨立 process。純 CPU，不用 --threads。
    with Pool(processes=6) as p:
        rows = p.map(one_point, gen, chunksize=1)

    print()
    for r in sorted(rows, key=lambda r: (r["Q"], r["D"], r["snr_db"])):
        print(f"  {r['tag']:22s} {'PASS' if r['ok'] else 'FAIL'}  "
              f"{r['n_bits']:>10,} bits  mismatch={r['mismatches']}  "
              f"SHA={'OK' if r['sha256_ok'] else 'BAD'}  "
              f"G6={'響了!' if r['g6_fired'] else '靜默'}  "
              f"{r['sim_khz']:.0f} kHz")

    with open(os.path.join(DATA, "tierb.json"), "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    n_ok = sum(r["ok"] for r in rows)
    tot_bits = sum(r["n_bits"] for r in rows)
    tot_stages = sum(r["n_stages"] for r in rows)
    print(f"\n{n_ok}/{len(rows)} 個點通過")
    print(f"TIERB_TOTAL {n_ok} {len(rows)} {tot_bits} {tot_stages}")
    return 0 if n_ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
