# -*- coding: utf-8 -*-
"""v122: why is the protagonist's 政体 word empty in the final piece? (fact-layer probe)"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402
import localization as L  # noqa: E402

data = os.path.join(ROOT, "output", "田所2", "data")
cache = json.load(open(os.path.join(data, "player_178021.json"), encoding="utf-8"))
melt = cl.load_melt(os.path.join(data, "melt_1120_01_01.json"))
_n = os.path.join(data, "names.json")
if not os.path.exists(_n):
    _n = os.path.join(ROOT, "data", "names.json")
names = json.load(open(_n, encoding="utf-8"))
f = F.Facts(cache, melt, names)
pid = cache["player_id"]
print("f.as_of =", repr(f.as_of), " last_date =", repr(cache.get("last_date")))
rec = (cache.get("characters") or {}).get(str(pid)) or {}
print("landed.government =", repr((rec.get("landed") or {}).get("government")))
print("cache schema =", cache.get("schema"))
for d in (None, "1119.7.15", "1119.1.1", "1118.1.1", "1095.1.1", "1093.1.1"):
    try:
        g = f._character_government(pid, d)
    except Exception as e:  # noqa: BLE001
        g = f"ERR {e}"
    print(f"  _character_government({d!r}) = {g!r}   zh={f._government_zh(g)!r}")
print("f.government(pid) =", repr(f.government(pid)))
print("loc[celestial_government] =", repr(L.loc(f.table, "celestial_government")))
print("home government history:",
      json.dumps((rec.get("government_history") or rec.get("char_government_history")) or [])[:400])
