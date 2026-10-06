# -*- coding: utf-8 -*-
"""One-off: print a cache's melt-relevant bookkeeping fields."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
folder = sys.argv[1] if len(sys.argv) > 1 else "洪氏2"
for pid in sys.argv[2:]:
    p = os.path.join(ROOT, "output", folder, "data", f"player_{pid}.json")
    c = json.load(open(p, encoding="utf-8"))
    print(f"player_{pid}: last_date={c.get('last_date')!r} first_date={c.get('first_date')!r} "
          f"folder={c.get('output_folder')!r} pt={c.get('playthrough_id')}")
    print("   sources:", (c.get("sources") or [])[-6:])
