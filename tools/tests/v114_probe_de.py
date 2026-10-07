# -*- coding: utf-8 -*-
"""v114 probe: who claims 99598/99599 (德娘/德) — cache-only."""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
CACHE = os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")
SNAP = os.path.join(ROOT, "output", "洪氏2", "data", "snap_v114_207044_final.json")
c = json.load(io.open(CACHE, encoding="utf-8"))
chars = c.get("characters") or {}
KEYS = ("primary_spouse", "spouse", "concubine", "former_spouses", "former_concubines",
        "child", "father", "mother", "siblings")
for cid in (99598, 99599):
    rec = chars.get(str(cid)) or {}
    print(f"== {cid} {rec.get('name')} house={rec.get('house')} birth={rec.get('birth')} "
          f"death={(rec.get('death') or {}).get('date')}")
    fam = rec.get("family") or {}
    for k in KEYS:
        v = fam.get(k)
        if v:
            print(f"   自记 {k}: {[f'{x}:{(chars.get(str(x)) or {}).get(chr(110)+chr(97)+chr(109)+chr(101))}' for x in v if isinstance(x, int)]}")
    print("   反向（谁记着他）:")
    for k, r in chars.items():
        f2 = r.get("family") or {}
        for key in KEYS:
            v = f2.get(key) or []
            if cid in [x for x in v if isinstance(x, int)]:
                print(f"     {k} {r.get('name')} field={key}")
print("\n==== 世系里出现「德娘」的行 ====")
d = json.load(io.open(SNAP, encoding="utf-8"))
for ln in d["facts"]["genealogy"]:
    if "德娘" in ln or "99598" in ln or "99599" in ln:
        print("  " + ln[:200])
