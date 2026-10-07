# -*- coding: utf-8 -*-
"""v114 probe: what the cache says about 尼各老's names (regnal_name, first_name, display_name)."""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import cache_lib as cl              # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
t0 = time.time()
cache = cl.load_cache(os.path.join(DATA, "player_207044.json"))
print(f"cache {time.time()-t0:.1f}s chars={len(cache.get('characters') or {})}")
rec = (cache.get("characters") or {}).get("67172818") or {}
print("cache rec keys:", sorted(rec.keys()))
for k in ("name_zh", "first_name", "regnal_name", "nickname", "nickname_zh", "dynasty",
          "house", "birth_name", "name"):
    if k in rec:
        print(f"   {k} = {rec[k]!r}")
print()
for fn, kw in (("display_name", {"ignore_regnal": False}), ("display_name", {"ignore_regnal": True})):
    try:
        v = cl.display_name(cache, 67172818, names_path=os.path.join(DATA, "names.json"), **kw)
        print(fn, kw, "->", v)
    except Exception as e:                                        # noqa: BLE001
        print(fn, kw, "ERR", e)
print()
print("snapshot-side name index rows mentioning 尼各老:")
snap = json.load(open(os.path.join(DATA, "snap_v114_207044_final.json"), encoding="utf-8"))
ni = snap["facts"].get("name_index") or {}
for k, v in (ni.items() if isinstance(ni, dict) else []):
    if "尼各老" in str(k) or "尼各老" in str(v):
        print("   ", k, "->", v)
