# -*- coding: utf-8 -*-
"""v114 probe (cache only, no melt): the `saint` trait interval's date precision."""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
CACHE = os.path.join(DATA, "player_207044.json")
SAINTS = [44503, 45152, 84824, 16878235, 83995743]

cache = json.load(io.open(CACHE, encoding="utf-8"))
chars = cache.get("characters") or {}
for cid in SAINTS:
    rec = chars.get(str(cid)) or {}
    th = rec.get("trait_history") or {}
    print(f"--- {cid} {rec.get('name_full') or rec.get('name_zh')!r} traits={rec.get('traits')}")
    for k, ivs in sorted(th.items()):
        print(f"    {k:28s} {json.dumps(ivs, ensure_ascii=False)}")
    print(f"    dead_data = {json.dumps(rec.get('dead_data'), ensure_ascii=False)[:400]}")
    print()

# how many characters in this cache hold the saint trait, and with which dates
n, dates = 0, {}
for cid, rec in chars.items():
    ivs = ((rec.get("trait_history") or {}).get("saint")) or []
    if ivs:
        n += 1
        for iv in ivs:
            dates[iv.get("from")] = dates.get(iv.get("from"), 0) + 1
print("cache 内带 saint 特质者:", n, " from 分布:", dates)
print("faiths.saints:", json.dumps((cache.get("faiths") or {}).get("saints"), ensure_ascii=False)[:300])
print("cache keys:", sorted(cache.keys()))
