"""v122 第3问取证五: 金元惠(16912738) 的附庸契约是什么样的, 我们的解码给出什么旗标。

用法: & tools\py.ps1 tools\tests\v122_probe_contract.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cache_lib as cl  # noqa: E402

DATA = r"output\田所2\data"
CID = 16912738
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


P(f"_CELESTIAL_PROVINCE_FLAGS = {getattr(cl, '_CELESTIAL_PROVINCE_FLAGS', None)}")
P(f"_CELESTIAL_PROVINCE_INDEX = {getattr(cl, '_CELESTIAL_PROVINCE_INDEX', None)}")
P()

for year in (1057, 1061, 1083):
    mp = os.path.join(DATA, f"melt_{year}_01_01.json")
    if not os.path.isfile(mp):
        P(f"({year} 档缺)")
        continue
    P(f"=== melt_{year}_01_01.json ===")
    db = (cl.load_melt_section(mp, "vassal_contracts") or {}).get("database") or {}
    P(f"  vassal_contracts.database 条数 = {len(db)}")
    hit = None
    for cid_key, rec in db.items():
        if not isinstance(rec, dict):
            continue
        try:
            v = int(rec.get("vassal"))
        except (TypeError, ValueError):
            continue
        if v == CID:
            hit = (cid_key, rec)
            break
    if hit:
        P(f"  契约 {hit[0]}: " + json.dumps(hit[1], ensure_ascii=False)[:900])
        P(f"  我们的解码 vassal_obligation_flags -> {cl.vassal_obligation_flags(hit[1])}")
    else:
        P(f"  没有 vassal == {CID} 的契约")
    # 该档里所有契约组名与旗标样例
    from collections import Counter
    groups = Counter()
    for rec in db.values():
        if isinstance(rec, dict):
            groups[str(rec.get("contract_group"))] += 1
    P(f"  契约组分布: {dict(groups)}")
    shown = 0
    for cid_key, rec in db.items():
        if not isinstance(rec, dict) or str(rec.get("contract_group")) != "meritocratic_vassal":
            continue
        P(f"  meritocratic_vassal 契约 {cid_key}: " + json.dumps(rec, ensure_ascii=False)[:500])
        P(f"    -> 解码 = {cl.vassal_obligation_flags(rec)}")
        shown += 1
        if shown >= 3:
            break
    P()

open(r"logs\v122_probe_contract.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122_probe_contract.txt")
