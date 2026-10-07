# -*- coding: utf-8 -*-
"""v114 probe (no melt): dump the tree's red edges, paths and 配 bead attachments."""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
t = json.load(io.open(os.path.join(ROOT, "output", "洪氏2", "data", "genealogy.json"),
                      encoding="utf-8"))
N = {n["id"]: n for n in t["nodes"]}
print("red_edges:")
for a, b, i in t["red_edges"]:
    print(f"  pair{i+1}: {a} {N[a]['name']}(g{N[a]['gen']}) -> {b} {N[b]['name']}(g{N[b]['gen']})")
print("pairs:")
for p in t["pairs"]:
    print("   " + " -> ".join(f"{x}:{N[x]['name']}(g{N[x]['gen']})" for x in p))
print("chain:", [(c["i"], c["id"], c["name"], c["gen"]) for c in t["chain"]])
print("配 珠:")
for n in t["nodes"]:
    if n["spouse_of"]:
        s = N.get(n["spouse_of"]) or {}
        print(f"  {n['id']} {n['name']}(g{n['gen']} {n['note']}) 配于 {n['spouse_of']} "
              f"{s.get('name')}(g{s.get('gen')}) word={n['spouse_word']}")
