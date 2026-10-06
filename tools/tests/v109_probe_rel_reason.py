# -*- coding: utf-8 -*-
"""One-off probe: relation reason sentence wording (v109 §2.5 evidence)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402

folder, pid = sys.argv[1], int(sys.argv[2])
kinds = sys.argv[3].split(",") if len(sys.argv) > 3 else ["friend", "rival", "grudge",
                                                          "nemesis", "soulmate",
                                                          "blood_brother", "lover"]
cache = json.load(open(os.path.join(ROOT, "output", folder, "data",
                                    f"player_{pid}.json"), encoding="utf-8"))
f = F.Facts(cache, {}, os.path.join(ROOT, "data", "names.json"))
chars = cache.get("characters") or {}
print("player:", (chars.get(str(pid)) or {}).get("name_zh"))
for kind in kinds:
    rows = f.relation_reasons(pid, (kind,)) or []
    print(f"\n-- {kind}: {len(rows)} reason(s)")
    for r in rows[:6]:
        print("   ", repr(r))
    # the pair form, over every recorded relation entry of the player
    for other in (sorted(((cache.get("relation_reasons") or {}).get(str(pid)) or {}))[:6]):
        try:
            o = int(other)
        except ValueError:
            continue
        pr = f.relation_reason_for_pair(pid, o, (kind,), styled=True)
        if pr:
            print(f"    pair {pid}/{o}: {pr[0]!r}")
