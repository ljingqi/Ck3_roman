# -*- coding: utf-8 -*-
"""v121 探针（四）：把所有聚合规则（_MERGE_SLOT_RES 同日、_AGG_SPEC 同月）逐条对快照
时间线跑一遍，列出「规则匹配不上 → 聚合静默失效」的类型与条数。

输出三块：
  [1] 同日规则 _MERGE_SLOT_RES：各类型总条数 / 不匹配条数 / 同组内 key 分裂情况
  [2] 同月规则 _AGG_SPEC：各类型总条数 / 不匹配条数 / 组条件不成立情况
  [3] 跨日规则 _ACTIVITY_MERGE_DAYS：同上
"""
import collections
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402

snaps = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, "output", "*", "data",
                                                      "snap_*.json")))
report = {}


def body_of(e):
    b = e.get("text") or ""
    m = re.match(r"^\d+年(?:\d+月(?:\d+日)?)?，", b)
    return b[m.end():] if m else b


for snap in snaps:
    try:
        d = json.load(open(snap, encoding="utf-8"))
    except Exception as ex:                                   # noqa: BLE001
        print("SKIP", snap, ex)
        continue
    f = d.get("facts") or {}
    tl = f.get("timeline") or []
    if not tl:
        continue
    print("=" * 72)
    print(os.path.relpath(snap, ROOT), " timeline =", len(tl))

    # [1] 同日
    print("  [1] 同日规则 _MERGE_SLOT_RES")
    by_type = collections.defaultdict(list)
    for e in tl:
        by_type[e.get("type")].append(e)
    for typ, spec in F._MERGE_SLOT_RES.items():
        es = by_type.get(typ) or []
        if not es:
            continue
        bad = [e for e in es if not re.match(spec["pat"], body_of(e))]
        print(f"      {typ}: 共{len(es)}条, 不匹配{len(bad)}条")
        for e in bad[:3]:
            print("         MISS:", body_of(e)[:90])

    # [2] 同月
    print("  [2] 同月规则 _AGG_SPEC")
    groups = collections.defaultdict(list)
    for e in tl:
        dt = str(e.get("date") or "")
        groups[(e.get("type"), ".".join(dt.split(".")[:2]))].append(e)
    for typ, spec in F._AGG_SPEC.items():
        es = by_type.get(typ) or []
        if not es:
            continue
        bad = [e for e in es if not re.match(spec["pat"], body_of(e))]
        print(f"      {typ}: 共{len(es)}条, 不匹配{len(bad)}条")
        for e in bad[:3]:
            print("         MISS:", body_of(e)[:90])
        # 组条件
        for (t2, ym), g in sorted(groups.items()):
            if t2 != typ or len(g) < 2:
                continue
            ms = [re.match(spec["pat"], body_of(e)) for e in g]
            if not all(ms):
                continue
            slots = [m.groups() for m in ms]
            if spec["style"] == "allies":
                ok = len({s[1] for s in slots}) == 1 and len({s[2] for s in slots}) == 1
                why = f"盟友{len({s[1] for s in slots})}方 敌手{len({s[2] for s in slots})}方"
            else:
                ok = len({s[1] for s in slots}) == 1 or len({s[0] for s in slots}) == 1
                why = (f"甲{len({s[0] for s in slots})}人 乙{len({s[1] for s in slots})}人")
            if not ok:
                print(f"         FAIL {ym} 共{len(g)}条: {why} -> 全月不聚合")

    # [3] 跨日
    print("  [3] 跨日规则 _ACTIVITY_MERGE_DAYS")
    for typ in F._ACTIVITY_MERGE_DAYS:
        es = by_type.get(typ) or []
        spec = F._MERGE_SLOT_RES.get(typ) or {}
        pat = spec.get("pat")
        bad = [e for e in es if pat and not re.match(pat, body_of(e))]
        print(f"      {typ}: 共{len(es)}条, 不匹配{len(bad)}条")
        for e in bad[:3]:
            print("         MISS:", body_of(e)[:90])
