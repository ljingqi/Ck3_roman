# -*- coding: utf-8 -*-
"""v114 probe: snapshot facts['characters'] / household_groups shape, for the uxorilocal question."""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

SNAP = os.path.join(ROOT, "output", "洪氏2", "data", "snap_v113_207044_final.json")
with io.open(SNAP, encoding="utf-8") as f:
    snap = json.load(f)
facts = snap.get("facts") or {}
ch = facts.get("characters")
print("characters type", type(ch).__name__, "n", len(ch) if hasattr(ch, "__len__") else "")
if isinstance(ch, dict):
    k = list(ch)[:3]
    for kk in k:
        print(" key", kk, "->", json.dumps(ch[kk], ensure_ascii=False)[:600])
elif isinstance(ch, list):
    print(json.dumps(ch[:2], ensure_ascii=False)[:800])
hg = facts.get("household_groups")
print("household_groups n", len(hg) if hasattr(hg, "__len__") else "")
print(json.dumps(hg[:1] if isinstance(hg, list) else hg, ensure_ascii=False)[:800])
print("name_index keys sample", list((facts.get("name_index") or {}).keys())[:5])
