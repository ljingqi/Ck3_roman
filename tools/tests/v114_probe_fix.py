# -*- coding: utf-8 -*-
"""v114 probe: build 洪七公's 1152 facts from the existing melt and check the five answers.

One melt load; prints the 世系 head lines, the saints list, the four cardinals' labels, the
genealogy tree's transmission paths and the 配/赘夫 beads.
"""
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import cache_lib as cl              # noqa: E402
import facts as F                   # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
CACHE = os.path.join(DATA, "player_207044.json")
MELT = os.path.join(DATA, "melt_1155_01_01.json")
NAMES = os.path.join(DATA, "names.json")

t0 = time.time()
cache = cl.load_cache(CACHE)
melt = cl.load_melt(MELT)
camp = {}
for fn in os.listdir(DATA):
    if fn.startswith("player_") and fn.endswith(".json"):
        try:
            pid = int(fn[len("player_"):-len(".json")])
        except ValueError:
            continue
        camp[pid] = cache if pid == 207044 else cl.load_cache(os.path.join(DATA, fn))
print(f"cache+melt+campaign in {time.time()-t0:.1f}s, campaign caches={len(camp)}")

f = F.Facts(cache, melt, NAMES, as_of="1152.11.13", campaign=camp)
facts = f.build()

print("\n==== ②③④ 世系头行 ====")
for ln in facts.get("genealogy") or []:
    if ln.startswith("**") or ln.startswith("世系图"):
        print("  " + ln)

print("\n==== ③ facts['saints'] ====")
for ln in facts.get("saints") or []:
    print("  " + ln)

print("\n==== ⑤ 枢机 ====")
for cid in (98860, 50426865, 67183293, 83949596):
    print(f"  {cid} {f.name_or(cid)}: official_title={f.official_title(cid)!r} "
          f"seat={f.cardinal_seat(cid)!r} label={f.person_label(cid, None, 'full')!r}")

print("\n==== ① 家谱 ====")
tree = facts.get("genealogy_tree") or {}
nodes = {n["id"]: n for n in tree.get("nodes") or []}
print(f"  nodes={len(nodes)} red_edges={len(tree.get('red_edges') or [])} "
      f"unreachable={tree.get('unreachable')}")
for i, p in enumerate(tree.get("pairs") or []):
    print(f"  pair{i+1}: " + " → ".join(f"{x} {f.name_or(x)}" for x in p))
print("  配珠/赘夫：")
for n in tree.get("nodes") or []:
    if n.get("spouse_of"):
        print(f"    {n['id']} {n['name']} ({n.get('spouse_word')}) → {n['spouse_of']} "
              f"{f.name_or(n['spouse_of'])}")
print("  尼各老 parent:", (nodes.get(67172818) or {}).get("parent"),
      f.name_or((nodes.get(67172818) or {}).get("parent")))
print("  洪地保 kids:", (nodes.get(33611550) or {}).get("kids"),
      "洪地香 kids:", (nodes.get(16836925) or {}).get("kids"))
