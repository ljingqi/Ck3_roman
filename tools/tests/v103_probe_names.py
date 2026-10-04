# -*- coding: utf-8 -*-
"""v103 probe: dump culture / name-order inputs for 洪真一, 大江笛, 耀国 from 耀国's cache.
Cache-only (no melt load). Writes logs/v103_probe_names.txt (UTF-8)."""
import json, os, sys, io
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
P = os.path.join(HERE, "output", "洪氏2", "data", "player_135480.json")
out = io.StringIO()
def w(*a):
    print(*a, file=out)

cache = json.load(open(P, encoding="utf-8"))
chars = cache.get("characters") or {}
pid = cache.get("player_id")
w("player_id", pid, "player_name", cache.get("player_name"),
  "house", cache.get("house_name"), "dyn", cache.get("dynasty_name"),
  "game_version", cache.get("game_version"))

def dump(cid, tag):
    r = chars.get(str(cid)) or {}
    w("\n==== %s cid=%s ====" % (tag, cid))
    for k in ("name_zh", "name_full", "house_name", "dynasty_name", "culture",
              "regnal_name", "female"):
        w("  %-14s %r" % (k, r.get(k)))
    w("  culture_history %r" % (r.get("culture_history"),))
    fam = r.get("family") or {}
    for k in ("father", "mother", "siblings", "primary_spouse", "spouse",
              "former_spouses", "child"):
        v = fam.get(k)
        if v:
            w("  family.%-14s %r" % (k, v))
    return r

# protagonist
dump(pid, "耀国(protagonist)")

# find 真一 / 大江 by name_zh
targets = []
for cid, r in chars.items():
    nm = r.get("name_zh") or ""
    if nm in ("真一", "笛") or "真一" in nm or (("大江" in nm) and len(nm) <= 3):
        targets.append((cid, nm))
w("\n# candidate ids by name_zh:", targets[:40])
for cid, nm in targets[:12]:
    dump(cid, "cand:" + nm)

with open(os.path.join(HERE, "logs", "v103_probe_names.txt"), "w", encoding="utf-8") as f:
    f.write(out.getvalue())
print("wrote logs/v103_probe_names.txt", len(out.getvalue()), "chars")
