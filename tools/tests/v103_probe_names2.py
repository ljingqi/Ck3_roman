# -*- coding: utf-8 -*-
"""v103 probe 2: exact records for mother(33666563), 笛(143983), and culture ids 82/271/307 etc."""
import json, os, sys, io
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
import cache_lib as cl
P = os.path.join(HERE, "output", "洪氏2", "data", "player_135480.json")
out = io.StringIO()
def w(*a): print(*a, file=out)

cache = json.load(open(P, encoding="utf-8"))
chars = cache.get("characters") or {}

def dump(cid, tag):
    r = chars.get(str(cid)) or {}
    w("\n==== %s cid=%s ====" % (tag, cid))
    for k in ("name_zh","name_full","house_name","dynasty_name","culture","regnal_name","female"):
        w("  %-14s %r" % (k, r.get(k)))
    w("  culture_history %r" % (r.get("culture_history"),))
    fam = r.get("family") or {}
    for k in ("father","mother","siblings","primary_spouse","spouse","former_spouses","child"):
        if fam.get(k): w("  family.%-14s %r" % (k, fam.get(k)))
    return r

dump(33666563, "母亲 真一")
dump(143983, "笛 (spouse)")
# father of mother, siblings, to see inference chain
r = chars.get("33666563") or {}
fam = r.get("family") or {}
for k in ("father","mother","siblings","primary_spouse","spouse"):
    for x in (fam.get(k) or [])[:4]:
        rr = chars.get(str(x)) or {}
        w("  [mother.%s] %s name_zh=%r culture=%r hist=%r" % (
            k, x, rr.get("name_zh"), rr.get("culture"), rr.get("culture_history")))
r2 = chars.get("143983") or {}
fam2 = r2.get("family") or {}
for k in ("father","mother","siblings","primary_spouse","spouse"):
    for x in (fam2.get(k) or [])[:4]:
        rr = chars.get(str(x)) or {}
        w("  [笛.%s] %s name_zh=%r culture=%r hist=%r" % (
            k, x, rr.get("name_zh"), rr.get("culture"), rr.get("culture_history")))

with open(os.path.join(HERE,"logs","v103_probe_names2.txt"),"w",encoding="utf-8") as f:
    f.write(out.getvalue())
print(out.getvalue())
