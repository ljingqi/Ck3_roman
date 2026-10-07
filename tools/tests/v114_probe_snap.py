# -*- coding: utf-8 -*-
"""v114 probe: what the newest facts snapshot carries for the four reported defects.

Usage: & tools\\py.ps1 tools\\tests\\v114_probe_snap.py
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
SNAP = os.path.join(DATA, "snap_v113_207044_final.json")

with io.open(SNAP, encoding="utf-8") as f:
    snap = json.load(f)
print("top keys:", sorted(snap.keys()))
facts = snap.get("facts") or {}
print("facts keys:", sorted(facts.keys()))
print()
for k in ("genealogy", "genealogy_tree"):
    v = facts.get(k)
    print("==", k, type(v).__name__)
    if isinstance(v, list):
        for ln in v:
            print("   ", ln)
    elif isinstance(v, dict):
        print("    nodes:", len(v.get("nodes") or []), "chain:", len(v.get("chain") or []))
        for c in v.get("chain") or []:
            print("    chain", c)
