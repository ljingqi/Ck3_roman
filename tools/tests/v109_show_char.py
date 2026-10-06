# -*- coding: utf-8 -*-
"""One-off: show the character records whose JSON mentions a given name."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pid = sys.argv[1]
tokens = sys.argv[2:]
cache = json.load(open(os.path.join(ROOT, "output", "洪氏2", "data",
                                    f"player_{pid}.json"), encoding="utf-8"))
chars = cache.get("characters") or {}
print("chars:", len(chars))
hits = []
for k, rec in chars.items():
    if not isinstance(rec, dict):
        continue
    s = json.dumps(rec, ensure_ascii=False)
    if any(t in s for t in tokens) or (k in tokens):
        hits.append(k)
print("hits:", len(hits), hits[:30])
for k in hits[:8]:
    r = {kk: vv for kk, vv in chars[k].items() if kk not in ("memories",)}
    print("\n", k, json.dumps(r, ensure_ascii=False)[:800])
