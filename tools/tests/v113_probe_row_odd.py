# -*- coding: utf-8 -*-
"""Which parent→child pairs break the 宝塔式 row order (child same row as, or above, its parent)?"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
t = json.load(io.open(os.path.join(ROOT, "output", "洪氏2", "data", "genealogy.json"),
                      encoding="utf-8"))
by = {n["id"]: n for n in t["nodes"]}
odd = []
for n in t["nodes"]:
    p = n["parent"]
    if p is None or p not in by or n["spouse_of"]:
        continue
    d = n["gen"] - by[p]["gen"]
    if d <= 0:
        odd.append((d, by[p], n))
for d, pa, ch in sorted(odd, key=lambda x: x[0]):
    print("d=%+d  父 %-12s gen=%d  子 %-12s gen=%d  from_k=%d/%d  归属 %s"
          % (d, pa["name"], pa["gen"], ch["name"], ch["gen"], pa["from_k"], ch["from_k"],
             ch["spouse_of"] or "血亲"))
print("共", len(odd), "对；总父子对",
      len([n for n in t["nodes"] if n["parent"] in by and not n["spouse_of"]]))
