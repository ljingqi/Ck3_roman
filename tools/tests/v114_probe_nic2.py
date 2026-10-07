# -*- coding: utf-8 -*-
"""v114 probe: name fields of 尼各老 as the snapshot sees them (chain label, characters entry, saints)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

SNAP = os.path.join(ROOT, "output", "洪氏2", "data", "snap_v114_207044_final.json")
facts = json.load(open(SNAP, encoding="utf-8"))["facts"]

chars = facts.get("characters") or {}
print("characters type:", type(chars), "len:", len(chars))
for cid in ("67172818", 67172818):
    if isinstance(chars, dict) and cid in chars:
        print(cid, json.dumps(chars[cid], ensure_ascii=False, indent=1)[:2000])
        break
print()
gi = facts.get("genealogy") or []
for line in gi:
    if "尼各老" in line or "四世" in line or "世系" in line:
        print("genealogy:", line)
print()
print("saints:", json.dumps(facts.get("saints"), ensure_ascii=False, indent=1))
print()
tl = facts.get("timeline") or []
print("timeline sample:", json.dumps(tl[:2], ensure_ascii=False)[:600])
