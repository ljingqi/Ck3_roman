# -*- coding: utf-8 -*-
"""v114 probe: read the built snapshot — saints block, tree spouse beads, transmission paths."""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
SNAP = os.path.join(ROOT, "output", "洪氏2", "data",
                    sys.argv[1] if len(sys.argv) > 1 else "snap_v114_207044_final.json")
d = json.load(io.open(SNAP, encoding="utf-8"))
for k, v in d["blocks"].items():
    txt = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    if "封圣" in txt:
        print(f"BLOCK {k}（{type(v).__name__}）")
        print("   " + txt[:400].replace("\n", "\n   "))
f = d["facts"]
t = f["genealogy_tree"]
nodes = {n["id"]: n for n in t["nodes"]}
print(f"\nnodes {len(nodes)} red_edges {len(t['red_edges'])} unreachable {t['unreachable']}")
print("pairs:")
for i, p in enumerate(t["pairs"]):
    print(f"  pair{i+1}: " + " → ".join(f"{x} {nodes[x]['name']}" for x in p))
print("配珠/赘夫：")
for n in t["nodes"]:
    if n.get("spouse_of"):
        print(f"  {n['id']} {n['name']} [{n.get('spouse_word')}] → "
              f"{n['spouse_of']} {(nodes.get(n['spouse_of']) or {}).get('name')}")
print("尼各老 parent:", nodes[67172818]["parent"],
      (nodes.get(nodes[67172818]["parent"]) or {}).get("name"))
print("洪地保 kids:", [nodes[x]["name"] for x in nodes[33611550]["kids"]])
print("洪地香 kids:", [nodes[x]["name"] for x in nodes[16836925]["kids"]])
print("洪天香 row:", {k: nodes[45152][k] for k in ("gen", "kids", "parent", "note", "from_k")})
print("赘夫 nodes:", [(n["id"], n["name"], n.get("spouse_word"), n.get("spouse_of"))
                    for n in t["nodes"] if n.get("spouse_word") == "赘夫"])
print("链:", " ─ ".join(f"{c['i']}{c['label']}" for c in t["chain"]))
print("题记:", t.get("summary"))
