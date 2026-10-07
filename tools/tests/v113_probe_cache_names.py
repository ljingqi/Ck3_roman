# -*- coding: utf-8 -*-
"""v113 probe: what name fields the campaign cache holds for the 传主 chain (names.json is
absent locally, so the HTML family tree must take names from the cache)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
DATA = os.path.join(ROOT, "output", "洪氏2", "data")

CHAIN = [38957, 44503, 67172818, 16879059, 16878235, 135480, 117484775, 16945142,
         207044, 33725392]

with open(os.path.join(DATA, "player_207044.json"), encoding="utf-8") as f:
    cache = json.load(f)
chars = cache.get("characters") or {}
print("cache characters:", len(chars), "| played_legacy:", len(cache.get("played_legacy") or []))
for cid in CHAIN:
    rec = chars.get(str(cid)) or {}
    print(f"\n{cid}: {json.dumps({k: rec.get(k) for k in ('name', 'name_zh', 'name_full', 'house', 'house_label', 'birth', 'death', 'culture')}, ensure_ascii=False)[:400]}")
    print("   all keys:", sorted(rec))
