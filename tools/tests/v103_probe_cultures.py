# -*- coding: utf-8 -*-
"""v103 probe 3: one melt load -> culture_manager facts for issues 1 & 2.
Extracts specific culture ids, name_order_convention distribution, hybrid markers,
and localized names. Writes logs/v103_probe_cultures.txt (UTF-8)."""
import json, os, sys, io
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
import cache_lib as cl
import localization as L
MELT = os.path.join(HERE, "output", "洪氏2", "data", "melt_1043_01_01.json.xz")
out = io.StringIO()
def w(*a): print(*a, file=out)

melt = cl.load_melt(MELT)
cm = (melt.get("culture_manager") or {})
cultures = cm.get("cultures") or {}
w("culture_manager top keys:", list(cm.keys()))
w("total cultures:", len(cultures))

# name_order_convention distribution
from collections import Counter
noc = Counter()
hyb = Counter()
for cid, e in cultures.items():
    if isinstance(e, dict):
        noc[e.get("name_order_convention") or "(empty)"] += 1
        # look for hybrid markers
        for k in e.keys():
            if "hybrid" in k.lower() or "parent" in k.lower():
                hyb[k] += 1
w("\nname_order_convention distribution:", dict(noc))
w("hybrid/parent-ish keys seen:", dict(hyb))

# dump one full culture entry to see all fields
sample = next(iter(cultures.values()))
w("\nSAMPLE culture entry keys:", list(sample.keys()) if isinstance(sample, dict) else type(sample))

table = L.table()
def dump_cul(cid):
    e = cultures.get(str(cid))
    w("\n---- culture id %s ----" % cid)
    if not isinstance(e, dict):
        w("   (absent)"); return
    for k, v in e.items():
        w("   %-24s %r" % (k, v))
    tpl = e.get("culture_template")
    nm = e.get("name")
    w("   => template=%r loc(template)=%r" % (tpl, L.loc(table, tpl) if tpl else None))
    if nm: w("   => loc(name)=%r" % (L.loc(table, str(nm)),))

for cid in (82, 271, 79, 119, 307):
    dump_cul(cid)

# find any culture whose template/localized name mentions 诺斯/norse or gaelic, list hybrids
w("\n== cultures with name_order_convention JAPANESE/DYNASTY_ALWAYS_FIRST (sample 15) ==")
n = 0
for cid, e in cultures.items():
    if isinstance(e, dict) and (e.get("name_order_convention") in ("JAPANESE","DYNASTY_ALWAYS_FIRST")):
        w("   %s tpl=%r noc=%r name=%r" % (cid, e.get("culture_template"),
          e.get("name_order_convention"), e.get("name")))
        n += 1
        if n >= 15: break

with open(os.path.join(HERE,"logs","v103_probe_cultures.txt"),"w",encoding="utf-8") as f:
    f.write(out.getvalue())
print("wrote logs/v103_probe_cultures.txt", len(out.getvalue()), "chars")
