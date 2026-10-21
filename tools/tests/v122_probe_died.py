"""v122 第1问取证: 1120.1.1 档的记忆库里, 有没有任何关于 178021 的「死」记忆。

用法: & tools\py.ps1 tools\tests\v122_probe_died.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cache_lib as cl  # noqa: E402

MELT = r"output\田所2\data\melt_1120_01_01.json"
CID = 178021
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


idx = cl.load_melt_index(MELT)
P(f"索引日期 = {idx.get('date')!r}; 记忆条数 = {len(idx.get('db') or {})}")
db = idx.get("db") or {}
hits = 0
for mid, e in db.items():
    if not isinstance(e, dict):
        continue
    parts = e.get("participants") or {}
    vals = []
    if isinstance(parts, dict):
        for k, v in parts.items():
            if isinstance(v, int):
                vals.append(v)
            elif isinstance(v, list):
                vals.extend(x for x in v if isinstance(x, int))
    if CID not in vals:
        continue
    typ = str(e.get("type") or "")
    if "die" in typ or "death" in typ:
        hit = True
    else:
        hit = False
    if hit:
        hits += 1
        P(f"  [死类记忆] {mid} type={typ!r} date={e.get('creation_date')!r} "
          f"end={e.get('end_date')!r} participants={parts}")
P(f"关于 {CID} 的死类记忆条数 = {hits}")
# 与他同日在场的那两条 1119.7.15 记忆再确认
P()
P("1119.7.15 前后涉及他的记忆:")
for mid, e in db.items():
    if not isinstance(e, dict):
        continue
    parts = e.get("participants") or {}
    vals = []
    if isinstance(parts, dict):
        for k, v in parts.items():
            if isinstance(v, int):
                vals.append(v)
            elif isinstance(v, list):
                vals.extend(x for x in v if isinstance(x, int))
    if CID in vals and str(e.get("creation_date") or "").startswith("1119.7"):
        P(f"  {mid} type={e.get('type')!r} date={e.get('creation_date')!r} "
          f"end={e.get('end_date')!r} vars={str(e.get('vars'))[:220]}")

open(r"logs\v122\v122_probe_died.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122/v122_probe_died.txt")
