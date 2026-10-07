# -*- coding: utf-8 -*-
"""v114 probe (snapshot only, seconds): generation numbers around 尼各老, the two 洪地香, and his name fields."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

SNAP = os.path.join(ROOT, "output", "洪氏2", "data", "snap_v114_207044_final.json")
snap = json.load(open(SNAP, encoding="utf-8"))
facts = snap["facts"]
tree = facts["genealogy_tree"]
nodes = {n["id"]: n for n in tree["nodes"]}

print("red_edges:", tree["red_edges"])
print("chain:")
for s in tree["chain"]:
    print("   ", s)
print()
print("nodes named 洪地香 / 尼各老 / 洪审礼 / 缯·洪堡 / 洪天香:")
for n in tree["nodes"]:
    if any(k in n["name"] for k in ("洪地香", "尼各老", "洪审礼", "缯·洪堡", "洪天香", "洪天贵福")):
        print("   ", json.dumps(n, ensure_ascii=False))
print()
print("gen histogram:", {})
hist = {}
for n in tree["nodes"]:
    hist[n.get("gen")] = hist.get(n.get("gen"), 0) + 1
print("   ", sorted(hist.items(), key=lambda kv: (kv[0] is None, kv[0])))
print()
for key in ("persons", "chars", "profile"):
    v = facts.get(key)
    if v is None:
        continue
    print(f"facts[{key!r}] keys sample:", list(v)[:5] if isinstance(v, dict) else type(v))
print()
print("facts keys:", sorted(facts.keys()))
