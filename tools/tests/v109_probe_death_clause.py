# -*- coding: utf-8 -*-
"""One-off probe: death_clause wording for given cids (v109 §2.5 evidence)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402

folder, pid = sys.argv[1], int(sys.argv[2])
cache = json.load(open(os.path.join(ROOT, "output", folder, "data",
                                    f"player_{pid}.json"), encoding="utf-8"))
f = F.Facts(cache, {}, os.path.join(ROOT, "data", "names.json"))
for cid in sys.argv[3:]:
    cid = int(cid)
    rec = (cache.get("characters") or {}).get(str(cid)) or {}
    d = rec.get("death") or {}
    print(f"{cid} {(cache.get('characters') or {}).get(str(cid), {}).get('name_zh')!r} "
          f"death={d.get('date')} reason={d.get('reason')!r} killer={d.get('killer')}")
    print("   death_clause       :", repr(f.death_clause(cid, date=d.get("date"))))
    print("   death_clause(impr) :", repr(f.death_clause(cid, date=d.get("date"), imprison=True)))
    print("   _death_sentence    :", repr(F._death_sentence(f, cid, killer_pronoun=True, insider=True)))
