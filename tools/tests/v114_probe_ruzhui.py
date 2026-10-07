# -*- coding: utf-8 -*-
"""v114 probe: everyone the snapshot records as 入赘, and whether the tree carries them."""
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
tree = facts.get("genealogy_tree") or {}
by_id = {int(k): v for k, v in (facts.get("characters") or {}).items()}
nodes = {n["id"]: n for n in tree.get("nodes") or []}
chain_ids = [c["id"] for c in tree.get("chain") or []]

print("== characters whose spouse lists carry 入赘 ==")
for cid, rec in sorted(by_id.items()):
    for key in ("spouses", "concubines", "former_spouses"):
        v = rec.get(key) or ""
        if "入赘" in v:
            n = nodes.get(cid)
            print(f"{cid} {'女' if rec.get('female') else '男'} {rec.get('label')!r}")
            print(f"    {key}: {v}")
            print(f"    children: {rec.get('children')!r}")
            print(f"    father: {rec.get('father')!r} mother: {rec.get('mother')!r}")
            if n:
                print(f"    TREE: node gen={n['gen']} subj={n['subj']} note={n['note']!r} "
                      f"parent={n['parent']} spouse_of={n['spouse_of']} kids={len(n['kids'])}")
            else:
                print("    TREE: MISSING")
            print()
print("== chain ids and their tree parent ==")
for c in chain_ids:
    n = nodes.get(c) or {}
    print(c, by_id.get(c, {}).get("label"), "parent", n.get("parent"),
          "parent label", (nodes.get(n.get("parent")) or {}).get("name"))
