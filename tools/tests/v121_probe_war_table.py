# -*- coding: utf-8 -*-
"""v121 探针（八）：把 agg_survey 报告汇总成「每个快照 war 行数 / 失败月数 / 失败行数」表。"""
import glob
import json
import os
import re
import sys
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402

snaps = sorted(glob.glob(os.path.join(ROOT, "output", "*", "data", "snap_*.json")))
rows = []
for snap in snaps:
    try:
        d = json.load(open(snap, encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        continue
    tl = (d.get("facts") or {}).get("timeline") or []
    if not tl:
        continue
    spec = F._AGG_SPEC["joined_allys_war"]
    groups = collections.defaultdict(list)
    for e in tl:
        dt = str(e.get("date") or "")
        if str(e.get("type")) != "joined_allys_war":
            continue
        groups[".".join(dt.split(".")[:2])].append(e)

    def body_of(e):
        b = e.get("text") or ""
        m = re.match(r"^\d+年(?:\d+月(?:\d+日)?)?，", b)
        return b[m.end():] if m else b

    n = sum(len(v) for v in groups.values())
    fm = fr = 0
    detail = []
    for ym, es in groups.items():
        if len(es) < 2:
            continue
        ms = [re.match(spec["pat"], body_of(e)) for e in es]
        if not all(ms):
            continue
        sl = [m.groups() for m in ms]
        if not (len({s[1] for s in sl}) == 1 and len({s[2] for s in sl}) == 1):
            fm += 1
            fr += len(es)
            detail.append(f"{ym}({len(es)})")
    if n:
        rows.append((os.path.relpath(snap, ROOT), len(tl), n, fm, fr, detail))
print(f"{'快照':<62}{'tl':>5}{'war':>6}{'失败月':>7}{'失败行':>7}")
for r in sorted(rows, key=lambda x: -x[4]):
    print(f"{r[0]:<62}{r[1]:>5}{r[2]:>6}{r[3]:>7}{r[4]:>7}   {' '.join(r[5][:10])}")
