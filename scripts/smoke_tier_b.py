"""Tier B 的煙霧測試：一個點、小規模，先確認整條路通了再放大。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.tier_b as tb  # noqa: E402

tb.FRAMES = 200
print("=== build")
tb.build(4, 10, 64)
print("=== gen")
g = tb.gen_point((4, 10, 64, 2.5, 3.0))
print("=== run")
r = tb.one_point(g)
for k, v in r.items():
    print(f"  {k:18s} {v}")
sys.exit(0 if r["ok"] else 1)
