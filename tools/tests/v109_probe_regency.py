# -*- coding: utf-8 -*-
"""v109 §2.1 regency evidence: load the cache plus the end-of-run melt and print the diarchies
records of this campaign together with `Facts.regency_of` / `identity_parts` words for
洪卡特琳 (67210684) as seen from 洪七公 (pid) and from 洪大力 (33725392).

The point of the two reference persons is the gate: a regency word may only be claimed for the
person the regent actually governs, never merely because she is somebody's regent.

Usage: & tools\\py.ps1 tools\\tests\\v109_probe_regency.py [family] [pid] [melt file]
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl        # noqa: E402
import facts as F            # noqa: E402

fam = sys.argv[1] if len(sys.argv) > 1 else "洪氏2"
pid = int(sys.argv[2]) if len(sys.argv) > 2 else 207044
data = os.path.join(ROOT, "output", fam, "data")
cache = json.load(io.open(os.path.join(data, f"player_{pid}.json"), encoding="utf-8"))

# The uncompressed melt holds the diarchies table; the slim `_idx` variant carries an empty
# database, so a probe pointed at `_idx` would report "no regency" for a campaign that has one.
melt_name = sys.argv[3] if len(sys.argv) > 3 else "melt_1155_01_01.json"
melt = cl.load_melt(os.path.join(data, melt_name))
print(f"熔件 {melt_name}")

db = ((melt.get("diarchies") or {}).get("database") or {})
print(f"diarchies.database 共 {len(db)} 条")
rows = []
for k, v in db.items():
    if not isinstance(v, dict):
        continue
    rows.append((str(v.get("start_date") or ""), k, v.get("type"), v.get("liege"),
                 v.get("diarch")))
rows.sort()
for st, k, ty, lg, di in rows[:6]:
    print(f"  {k} type={ty} liege={lg} diarch={di} start={st}")
print(f"  … 共 {len(rows)} 条")

f = F.build_facts(cache, melt, as_of=None)["_facts"]
print(f"\nFacts._regencies = {len(f._regencies)}")
for e in f._regencies:
    if e["diarch"] == 67210684 or e["liege"] in (pid, 33725392):
        print(f"  {e}  词={F.L.diarchy_type_word(f.table, e['type'])!r}")
for cid in (67210684, 33725392):
    print(f"\ncid={cid}")
    print(f"  regency_of            = {f.regency_of(cid)!r}")
    print(f"  regent_of(33725392)   = {f.regent_of(33725392)!r}")
    for subj in (pid, 33725392):
        print(f"  identity_parts(rel {subj}) = {f.identity_parts(cid, subj)}")
