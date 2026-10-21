"""v122 第3问取证六: 游戏自己给 金元惠(16912738) 烘焙了什么 dead_data.flavor。

用法: & tools\py.ps1 tools\tests\v122_probe_flavor.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cache_lib as cl  # noqa: E402

DATA = r"output\田所2\data"
CID = "16912738"
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


for year in (1061, 1062, 1083):
    mp = os.path.join(DATA, f"melt_{year}_01_01.json")
    if not os.path.isfile(mp):
        continue
    P(f"=== melt_{year}_01_01.json ===")
    for sec in ("living", "dead_unprunable"):
        d = cl.load_melt_section(mp, sec) or {}
        rec = d.get(CID)
        if isinstance(rec, list):
            rec = rec[0]
        if not rec:
            continue
        P(f"  [{sec}] first_name={rec.get('first_name')!r} keys={sorted(rec.keys())}")
        P(f"    dead_data = " + str(rec.get("dead_data"))[:600])
        P(f"    landed_data.government = {(rec.get('landed_data') or {}).get('government')!r}")
    dp = cl.load_melt_section(mp, "characters") or {}
    sub = (dp.get("dead_prunable") or {}) if isinstance(dp, dict) else {}
    rec = sub.get(CID)
    if rec:
        P(f"  [dead_prunable] dead_data = " + str((rec if isinstance(rec, dict) else rec[0]).get("dead_data"))[:600])
    P()

open(r"logs\v122\v122_probe_flavor.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122/v122_probe_flavor.txt")
