# -*- coding: utf-8 -*-
"""v114 probe: the 家谱 tree alone (cache + melt, no campaign, ~15s) — spouse beads and red paths."""
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import cache_lib as cl              # noqa: E402
import facts as F                   # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
t0 = time.time()
cache = cl.load_cache(os.path.join(DATA, "player_207044.json"))
melt = cl.load_melt(os.path.join(DATA, "melt_1155_01_01.json"))
print(f"载入 {time.time()-t0:.1f}s", flush=True)
f = F.Facts(cache, melt, os.path.join(DATA, "names.json"), as_of=None)
t = F.genealogy_tree(f)
nodes = {n["id"]: n for n in t["nodes"]}
print(f"nodes={len(nodes)} red={len(t['red_edges'])} unreachable={t['unreachable']} "
      f"summary={t.get('summary')}")
print("pairs:")
for i, p in enumerate(t["pairs"]):
    print(f"  pair{i+1}: " + " → ".join(f"{x} {nodes[x]['name']}" for x in p))
print("配珠/赘夫：")
for n in t["nodes"]:
    if n.get("spouse_of"):
        print(f"  {n['id']} {n['name']} [{n.get('spouse_word')}] → "
              f"{n['spouse_of']} {(nodes.get(n['spouse_of']) or {}).get('name')}")
orphan = [n["id"] for n in t["nodes"]
          if n["id"] != t["chain"][0]["id"] and not n.get("parent") and not n.get("spouse_of")]
print("无归属:", [(x, nodes[x]["name"]) for x in orphan])
