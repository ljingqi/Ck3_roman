# -*- coding: utf-8 -*-
"""v114 probe (cache only): the `saint` interval as each campaign cache sees it.

The caches of one campaign were built from different melt windows, so the first cache that shows the
trait brackets the canonization between two observation dates.
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
SAINTS = [44503, 45152, 84824, 16878235, 83995743, 16836925]

rows = []
for fn in sorted(os.listdir(DATA)):
    if not (fn.startswith("player_") and fn.endswith(".json") and ".tmp" not in fn):
        continue
    pid = fn[len("player_"):-len(".json")]
    try:
        c = json.load(io.open(os.path.join(DATA, fn), encoding="utf-8"))
    except Exception as e:                                        # noqa: BLE001
        print(f"{fn}: 读取失败 {e}")
        continue
    chars = c.get("characters") or {}
    print(f"== {fn}  last_date={c.get('last_date')!r}  角色数={len(chars)}")
    # the earliest snapshot the cache saw, from any character's first_location / trait history
    earliest = None
    for rec in chars.values():
        for key in ("trait_history", "location_history", "prison_history"):
            for ivs in (rec.get(key) or {}).values() if isinstance(rec.get(key), dict) else []:
                for iv in ivs:
                    d = iv.get("from")
                    if d and (earliest is None or str(d) < str(earliest)):
                        earliest = str(d)
        fl = rec.get("first_location") or {}
        if fl.get("date") and (earliest is None or str(fl["date"]) < str(earliest)):
            earliest = str(fl["date"])
    print(f"   最早观测日 = {earliest!r}")
    for cid in SAINTS:
        rec = chars.get(str(cid)) or {}
        if not rec:
            continue
        ivs = (rec.get("trait_history") or {}).get("saint")
        allth = rec.get("trait_history") or {}
        first_dates = sorted({str(iv.get("from")) for k, l in allth.items() for iv in l
                              if iv.get("first")})
        print(f"   {cid} {rec.get('name_full') or rec.get('name_zh')!r}: saint={json.dumps(ivs, ensure_ascii=False)}"
              f"  其它特质的 first 观测日={first_dates[:3]}")
        if ivs:
            rows.append((pid, cid, ivs))
io.open(os.path.join(ROOT, "logs", "v114_saint_caches.txt"), "w", encoding="utf-8").write(
    json.dumps(rows, ensure_ascii=False, indent=1))
