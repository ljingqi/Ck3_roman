# -*- coding: utf-8 -*-
"""v121 探针（六）：找「同一天同类型」大簇 —— 除已发现的 joined_allys_war 之外，
还有哪些类型会在一天里刷出十几行。只读快照，不载熔件。
"""
import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
snaps = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, "output", "*", "data",
                                                      "snap_*.json")))
worst = collections.Counter()
for snap in snaps:
    try:
        d = json.load(open(snap, encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        continue
    tl = (d.get("facts") or {}).get("timeline") or []
    if not tl:
        continue
    g = collections.Counter((e.get("date"), e.get("type")) for e in tl)
    big = [(n, k) for k, n in g.items() if n >= 5]
    if big:
        print("=" * 70)
        print(os.path.relpath(snap, ROOT), " timeline =", len(tl))
        for n, k in sorted(big, reverse=True):
            print(f"   {n:>3} 行  {k[1]}  {k[0]}")
            worst[k[1]] += n
print("\n跨快照累计最大的类型：")
for t, n in worst.most_common(20):
    print(f"   {n:>5}  {t}")
