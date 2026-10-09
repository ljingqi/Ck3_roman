"""v118 check · blast radius: what changed in the facts between two snapshots.

Both files must be snapshot-shaped (`{schema, meta, facts, shared, blocks, messages}`). Prints the
top-level and `facts` key differences, then per-list differences for the facts that matter for this
round (killed / genealogy / saints / timeline / characters ...), and a per-block text diff summary.

Usage: & tools\\py.ps1 tools\\tests\\v118_diff_snap.py <old.json> <new.json>
"""
import json
import re
import sys
from pathlib import Path

LISTS = ("killed", "genealogy", "timeline", "saints", "characters", "siblings", "reigns",
         "seat_succession", "sainthood", "house_history")


def key_of(x):
    if isinstance(x, dict):
        for k in ("id", "cid", "text", "name", "date"):
            if k in x:
                return (k, str(x[k]))
        return ("<dict>", json.dumps(x, ensure_ascii=False, sort_keys=True)[:120])
    return ("<scalar>", str(x))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    a = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    b = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    print(f"old = {sys.argv[1]}")
    print(f"new = {sys.argv[2]}")
    print(f"top keys: {sorted(a)} -> {sorted(b)}")
    fa, fb = a.get("facts") or {}, b.get("facts") or {}
    only_a = sorted(set(fa) - set(fb))
    only_b = sorted(set(fb) - set(fa))
    print(f"facts keys: {len(fa)} -> {len(fb)}  only-old={only_a} only-new={only_b}")
    for k in sorted(set(fa) & set(fb)):
        va, vb = fa[k], fb[k]
        if type(va) is not type(vb):
            print(f"  [{k}] type {type(va).__name__} -> {type(vb).__name__}")
            continue
        if isinstance(va, list):
            if len(va) != len(vb):
                print(f"  [{k}] list {len(va)} -> {len(vb)}")
                ka = {key_of(x) for x in va}
                kb = {key_of(x) for x in vb}
                for x in sorted(kb - ka)[:8]:
                    print(f"      + {x}")
                for x in sorted(ka - kb)[:8]:
                    print(f"      - {x}")
        elif isinstance(va, dict):
            if set(va) != set(vb):
                print(f"  [{k}] dict keys only-old={sorted(set(va) - set(vb))[:6]} "
                      f"only-new={sorted(set(vb) - set(va))[:6]}")
        elif va != vb:
            print(f"  [{k}] {str(va)[:70]!r} -> {str(vb)[:70]!r}")
    # messages / blocks: report only size and per-block drift
    for k in ("messages", "blocks", "shared"):
        va, vb = a.get(k), b.get(k)
        if isinstance(va, dict) and isinstance(vb, dict):
            same = [x for x in set(va) & set(vb) if va[x] == vb[x]]
            diff = [x for x in set(va) | set(vb) if va.get(x) != vb.get(x)]
            print(f"{k}: {len(va)} -> {len(vb)}, identical={len(same)}, differing={len(diff)} "
                  f"{diff[:6]}")
        elif isinstance(va, str) and isinstance(vb, str):
            print(f"{k}: {len(va)} -> {len(vb)} chars, identical={va == vb}")
    # the two spots of this round
    for tag, snap in (("OLD", a), ("NEW", b)):
        f = snap.get("facts") or {}
        k = f.get("killed") or []
        print(f"{tag} killed: {len(k)} -> " +
              ", ".join(str(e.get("name")) for e in k))
        g = "\n".join(f.get("genealogy") or [])
        heads = [ln for ln in g.splitlines() if re.match(r"^\*\*[一二三四五六七八九十]+世\*\*$", ln)]
        print(f"{tag} genealogy heads: {len(heads)}; "
              f"placeholders={'某人' in g}")


if __name__ == "__main__":
    main()
