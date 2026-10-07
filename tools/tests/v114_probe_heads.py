# -*- coding: utf-8 -*-
"""v114 probe: the 世系 head lines of the newest snapshot that carries a genealogy."""
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
best = None
for p in glob.glob(os.path.join(ROOT, "output", "洪氏2", "data", "*.json")):
    if os.path.basename(p).startswith(("player_", "melt_")):
        continue
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception:
        continue
    f = (d.get("facts") or {})
    if f.get("genealogy_tree") and d.get("player_id") == 207044:
        best = (os.path.getmtime(p), p, f)
if not best:
    print("找不到快照")
    sys.exit(0)
print("快照:", os.path.basename(best[1]))
for ln in best[2].get("genealogy") or []:
    if ln.startswith("**") or ln.startswith("### ") or ln.startswith("世系图") or ln.startswith("凡例"):
        print("  " + ln)
