# -*- coding: utf-8 -*-
"""v114 probe: chain labels + which node carries which label (the four reported defects)."""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
SNAP = os.path.join(DATA, "snap_v113_207044_final.json")
with io.open(SNAP, encoding="utf-8") as f:
    snap = json.load(f)
tree = (snap.get("facts") or {}).get("genealogy_tree") or {}
for c in tree.get("chain") or []:
    print(c["i"], c["id"], c["gen"], repr(c["name"]), "|", repr(c["label"]), c["date"])
print()
print("== nodes named like the report ==")
for n in tree.get("nodes") or []:
    if n["id"] in (44503, 16878235, 135480, 117484775, 16945142, 207044):
        print(n["id"], "gen", n["gen"], "subj", n["subj"], "sex", n["sex"],
              "| name", repr(n["name"]), "| label", repr(n["label"]), "| note", n["note"],
              "| parent", n["parent"], "| spouse_of", n["spouse_of"], "| kids", n["kids"])
print()
print("== chain pairs / unreachable ==")
print("red_dashed", tree.get("red_dashed"))
print("unreachable", tree.get("unreachable"))
for p in tree.get("pairs") or []:
    print("pair path", p)
print()
print("== all women with recorded children ==")
chars = (snap.get("facts") or {}).get("characters") or {}
node_ids = {n["id"] for n in tree.get("nodes") or []}
fams = (snap.get("facts") or {}).get("household_groups")
print("household_groups type", type(fams).__name__)
