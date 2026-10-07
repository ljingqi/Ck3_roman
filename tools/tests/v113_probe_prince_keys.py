# -*- coding: utf-8 -*-
"""v113 probe: which localization keys give the 王子/公子/皇子/公女/公主 words (no melt)."""
import collections
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
WORDS = ["王子", "公子", "公女", "皇子", "皇女", "公主"]


def main():
    t = json.load(io.open(os.path.join(ROOT, "data", "localization.json"),
                          encoding="utf-8"))["table"]
    flav = json.load(io.open(os.path.join(ROOT, "data", "flavorization.json"),
                             encoding="utf-8"))["entries"]
    hits = {w: [] for w in WORDS}
    for k, v in t.items():
        for w in WORDS:
            if isinstance(v, str) and v.endswith(w) and len(v) <= 4:
                hits[w].append((k, v))
    for w in WORDS:
        print(f"\n=== 「{w}」（{len(hits[w])} 键）===")
        for k, v in sorted(hits[w])[:14]:
            e = flav.get(k) or {}
            print(f"    {k:<44} {v:<6} tier={e.get('tier','')} gender={e.get('gender','')} "
                  f"gov={','.join(e.get('governments') or [])}")


if __name__ == "__main__":
    main()
