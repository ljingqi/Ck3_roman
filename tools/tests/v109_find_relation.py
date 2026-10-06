# -*- coding: utf-8 -*-
"""Locate the characters named on the command line inside the campaign caches.

Read-only probe: scans `output/<folder>/data/player_*.json` for the given names
without parsing the whole file first (a byte scan keeps 200-400MB caches out of
memory), then loads only the caches that actually contain a hit and prints each
character's cid, sex, birth/death, family edges and game relations.

Usage:
    & tools\\py.ps1 tools\\tests\\v109_find_relation.py <folder> <name> [name…]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402


def _contains(path, needles):
    """Byte-scan the file for any needle; return the set of needles found."""
    hits = set()
    blobs = [n.encode("utf-8") for n in needles]
    with open(path, "rb") as fp:
        tail = b""
        while True:
            chunk = fp.read(8 << 20)
            if not chunk:
                break
            buf = tail + chunk
            for n, b in zip(needles, blobs):
                if n not in hits and b in buf:
                    hits.add(n)
            tail = buf[-64:]
    return hits


def _dump(folder, pid, names):
    path = os.path.join(ROOT, "output", folder, "data", f"player_{pid}.json")
    cache = json.load(open(path, encoding="utf-8"))
    chars = cache.get("characters") or {}
    rev = F.kin_rev_index(chars)
    label = {}
    for k, rec in chars.items():
        if not k.isdigit() or not isinstance(rec, dict):
            continue
        nm = rec.get("name") or ""
        if nm in names:
            label.setdefault(nm, []).append(int(k))
    print(f"\n=== player_{pid}.json  传主 {cache.get('player_name')} "
          f"playthrough {cache.get('playthrough_id')} ===")
    for nm in names:
        for cid in label.get(nm, []):
            rec = chars[str(cid)] or {}
            fam = rec.get("family") or {}
            print(f"\n-- {nm} (cid {cid})")
            print("   birth/death:", rec.get("birth"), "/", rec.get("death"))
            print("   sex:", "F" if F._female_rec(rec) else "M")
            for key in ("father", "real_father", "mother", "primary_spouse", "spouse",
                        "concubine", "child", "siblings"):
                v = fam.get(key)
                if v:
                    print(f"   {key}: {v}")
            print("   rev.sib:", (rev.get("sib") or {}).get(cid))
            print("   rev.kid:", (rev.get("kid") or {}).get(cid))
            for key in ("relations", "relation", "scripted_relations"):
                if rec.get(key):
                    print(f"   {key}: {rec.get(key)}")
                elif cache.get(key) and str(cid) in cache.get(key):
                    print(f"   cache[{key}][{cid}]: {cache[key][str(cid)]}")
            off = cache.get("court_positions") or {}
            mine = {k: v for k, v in off.items() if str(v.get("character")) == str(cid)}
            if mine:
                print("   court_positions:", json.dumps(mine, ensure_ascii=False)[:400])
    return label


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    folder, names = sys.argv[1], sys.argv[2:]
    data = os.path.join(ROOT, "output", folder, "data")
    cands = []
    for fn in sorted(os.listdir(data)):
        if fn.startswith("player_") and fn.endswith(".json"):
            cands.append((fn, os.path.getsize(os.path.join(data, fn))))
    found = {}
    for fn, size in cands:
        try:
            hits = _contains(os.path.join(data, fn), names)
        except OSError:
            continue
        if hits:
            print(f"{fn} ({size:,} B) 命中 {sorted(hits)}")
            found[fn] = hits
    for fn in found:
        pid = int(fn[len("player_"):-len(".json")])
        _dump(folder, pid, names)
    return 0


if __name__ == "__main__":
    sys.exit(main())
