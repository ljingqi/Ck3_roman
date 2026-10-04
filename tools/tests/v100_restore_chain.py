# -*- coding: utf-8 -*-
"""v100: restore the campaign's played-character chain in this folder's caches (tools/tests only).

`rebuild_folder.py` rebuilds a cache from the melts, and a melt's `played_character.legacy` stops at
the player of that save: the successors a *later* save records are written into the earlier caches by
pipeline.py's reign-end path. An empty-cache rebuild therefore drops them, which costs the
《王朝历代》 closing line its 「其后传主之位归于…」 clause (facts._chrono_next_player) and the
传主档案 its successor sentence (facts.succession_lines).

The later caches (16879059 / 16878235) hold the full chain, so this writes it back into every cache of
the same campaign that is missing entries. Only `played_legacy` is touched.

Usage:  & tools\\py.ps1 tools\\tests\\v100_restore_chain.py [--write]
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "output", "洪氏2", "data")
WRITE = "--write" in sys.argv

caches = {}
for p in sorted(glob.glob(os.path.join(DATA, "player_*.json"))):
    if not os.path.basename(p).endswith(".json") or ".pre_" in p:
        continue
    caches[p] = json.load(open(p, encoding="utf-8"))

# The longest chain wins: the same campaign chain, seen by the last save that still lists a player.
best, best_len = None, 0
for p, c in caches.items():
    ch = [e for e in (c.get("played_legacy") or [])
          if isinstance(e, dict) and isinstance(e.get("cid"), int)]
    if len(ch) > best_len:
        best, best_len = ch, len(ch)
print("full chain (%d): %s" % (best_len, [(e.get("cid"), e.get("date")) for e in best]))

for p, c in caches.items():
    ch = [e for e in (c.get("played_legacy") or [])
          if isinstance(e, dict) and isinstance(e.get("cid"), int)]
    if len(ch) >= best_len:
        print("  %s: %d entries, nothing to do" % (os.path.basename(p), len(ch)))
        continue
    print("  %s: %d -> %d entries%s"
          % (os.path.basename(p), len(ch), best_len, "" if WRITE else "  (dry run)"))
    if WRITE:
        c["played_legacy"] = [dict(e) for e in best]
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(c, fp, ensure_ascii=False)
print("written" if WRITE else "dry run only (pass --write)")
