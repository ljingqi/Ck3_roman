# -*- coding: utf-8 -*-
"""v114 probe: for every recorded mother/father in the snapshot household, where the tree hangs
the child (mother vs father), and whether the parent is on the tree at all."""
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
label_to_id = {n["label"]: n["id"] for n in tree.get("nodes") or []}
label_to_id.update({n["name"]: n["id"] for n in tree.get("nodes") or []})

print("household records:", len(by_id))
print()
for cid, rec in sorted(by_id.items(), key=lambda kv: str(kv[1].get("label"))):
    fa, mo = rec.get("father") or "", rec.get("mother") or ""
    fid, mid = label_to_id.get(fa), label_to_id.get(mo)
    n = nodes.get(cid)
    if not n:
        print(f"{cid} {rec.get('label')!r} sex={'女' if rec.get('female') else '男'} NOT ON TREE; fa={fa!r} mo={mo!r}")
        continue
    par = n["parent"]
    role = "?"
    if par is not None and fid is not None and mid is not None:
        role = "父" if par == fid else ("母" if par == mid else "其他")
    elif par is not None and fid is not None:
        role = "父" if par == fid else "?"
    elif par is not None and mid is not None:
        role = "母" if par == mid else "?"
    print(f"{cid} {rec.get('label')!r} note={n['note']!r} gen={n['gen']} "
          f"parent={par} ({'父' if fid == par else ('母' if mid == par else '-')}) "
          f"kids={len(n['kids'])} fa={fa!r} mo={mo!r}")
