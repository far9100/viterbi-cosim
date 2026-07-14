"""R1 的裁決材料：SNR 依賴到底住在哪裡？（用已經落快取的點）"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.gates import DATA  # noqa: E402

rows = []
for f in glob.glob(os.path.join(DATA, "cache_m5", "Q4_W10_D64_snr*_f3.json")):
    with open(f) as fh:
        rows.append(json.load(fh))
rows.sort(key=lambda r: r["snr_db"])
if len(rows) < 3:
    print("點數不足")
    sys.exit(0)

B = ["u_tb", "u_acs", "u_minpm", "u_bmu", "u_ctrl"]

print("=== 總功耗與內部/翻轉的拆解（Q=4 W=10 D=64 @ 100 MHz）")
print(f"{'SNR':>5} {'總':>8} | {'internal':>9} {'switching':>10} {'leak(µW)':>9}")
for r in rows:
    print(f"{r['snr_db']:>5.0f} {r['p_total_w']*1e3:>7.3f}m | "
          f"{r['p_total_int_w']*1e3:>8.3f}m {r['p_total_sw_w']*1e3:>9.3f}m "
          f"{r['p_total_leak_w']*1e6:>8.2f}")

print()
print("=== 每個區塊的 **switching**（資料相依的那一部分）")
hdr = "".join(f"{b:>12}" for b in B)
print(f"{'SNR':>5}{hdr}")
for r in rows:
    line = "".join(f"{r.get(f'p_{b}_sw_w', 0)*1e3:>11.4f}m" for b in B)
    print(f"{r['snr_db']:>5.0f}{line}")

print()
print("=== 1 -> 5 dB 的變動幅度")
def var(key):
    v = [r.get(key, 0.0) for r in rows]
    return 100.0 * (max(v) - min(v)) / max(v) if max(v) > 0 else 0.0

print(f"  總功耗          {var('p_total_w'):6.2f}%")
print(f"  總 internal     {var('p_total_int_w'):6.2f}%   <- 時脈驅動，與 SNR 無關")
print(f"  總 switching    {var('p_total_sw_w'):6.2f}%   <- 資料驅動")
for b in B:
    print(f"  {b:8s} sw    {var(f'p_{b}_sw_w'):6.2f}%")

print()
print("=== 功耗的組成（3 dB）")
r = [x for x in rows if x["snr_db"] == 3.0][0]
tot = r["p_total_w"]
for b in B:
    p = r.get(f"p_{b}_w", 0)
    pi = r.get(f"p_{b}_int_w", 0)
    ps = r.get(f"p_{b}_sw_w", 0)
    if p > 0:
        print(f"  {b:8s} {p*1e3:7.3f} mW ({100*p/tot:5.1f}%)  "
              f"internal {pi*1e3:6.3f} ({100*pi/max(p,1e-12):4.1f}%)  "
              f"switching {ps*1e3:6.3f}")
print(f"  {'總計':8s} {tot*1e3:7.3f} mW   "
      f"internal {r['p_total_int_w']*1e3:.3f} ({100*r['p_total_int_w']/tot:.1f}%)  "
      f"switching {r['p_total_sw_w']*1e3:.3f} ({100*r['p_total_sw_w']/tot:.1f}%)")
