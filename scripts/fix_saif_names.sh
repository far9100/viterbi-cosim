#!/usr/bin/env bash
# 修 SAIF 檔名碰撞：act_<tag>_snr<snr>.saif 沒把 frames 放進檔名，
# 於是收斂性用的 f1/f2 run 覆寫了主 run（f3）的 SAIF。
#
# 受影響的只有 Q4_W10_D64 @ 3.0 dB（只有它跑了 f1/f2）。實證：那個 SAIF 只有
# 2204 cycles（≈2 frame），但快取的點寫 n_stages: 3090（3 frame）。
#
# 另外 7 個點只跑過 f3，內容是對的，只要改名。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh          # oss-cad-suite（iverilog/vvp）+ venv 的 PATH

echo "=== 1. 把 7 個正確的 f3 SAIF 改名（加上 _f3）"
for f in data/saif/act_*.saif; do
  b=$(basename "$f" .saif)
  case "$b" in
    *_f[0-9]*) echo "    已有 frames 後綴，跳過: $b"; continue ;;
    act_Q4_W10_D64_snr3.0) echo "    受污染，刪除待重生: $b"; rm -f "$f"; continue ;;
  esac
  mv "$f" "data/saif/${b}_f3.saif"
  echo "    $b -> ${b}_f3"
done

echo
echo "=== 2. 清掉 Q4_W10_D64 @ 3.0 dB 的 3 個功耗快取，強制重跑"
echo "    （重跑會重生 SAIF，而且新算出的功耗必須與先前回報的一致——這是一次可重生性測試）"
for f in 1 2 3; do
  p="data/cache_m5/Q4_W10_D64_snr3.0_f${f}.json"
  if [ -f "$p" ]; then
    python3 - "$p" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(f"    先前回報 f{d['frames']}: P_total = {d['p_total_w']*1e3:.3f} mW  "
      f"(tb {d.get('p_u_tb_w',0)*1e3:.3f}, acs {d.get('p_u_acs_w',0)*1e3:.3f})")
PY
    mv "$p" "${p}.pre_fix"
  fi
done

echo
echo "=== 3. 重跑（ppa/run_power.py 會續跑：其他 7 點命中快取，只重算這 3 點）"
python3 ppa/run_power.py

echo
echo "=== 4. 可重生性檢查：重算的功耗 vs 修正前回報的功耗"
python3 - <<'PY'
import json, os, sys
bad = 0
for f in (1, 2, 3):
    new = f"data/cache_m5/Q4_W10_D64_snr3.0_f{f}.json"
    old = new + ".pre_fix"
    if not (os.path.exists(new) and os.path.exists(old)):
        print(f"    f{f}: 尚未重生，跳過")
        continue
    n = json.load(open(new)); o = json.load(open(old))
    dp = abs(n["p_total_w"] - o["p_total_w"]) / o["p_total_w"] * 100
    ok = dp < 0.01
    bad += (not ok)
    print(f"    f{f}: 舊 {o['p_total_w']*1e3:.4f} mW  新 {n['p_total_w']*1e3:.4f} mW  "
          f"Δ={dp:.4f}%  {'OK' if ok else '**不一致**'}")
sys.exit(1 if bad else 0)
PY

echo
echo "=== 5. 最終的 SAIF 檔案清單"
ls -la data/saif/
