# -*- coding: utf-8 -*-
"""v117 check (item 4b regression): exactly what did the surname fix change in a facts snapshot?

Walks two `snap.py` snapshots of the same volume and prints every differing leaf fragment. The
v117 ④b fix may only ADD the clan surname 「洪」 where a character's record is absent from the
cache; any deletion or replacement is a regression.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_4b_diff.py <旧快照> <新快照>
"""
import difflib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(ROOT, "logs", "v117_check_4b_diff.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def leaves(o, path=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, path + (str(k),))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, path + (f"[{i}]",))
    else:
        yield "/".join(path), o


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    old = json.load(open(sys.argv[1], encoding="utf-8"))
    new = json.load(open(sys.argv[2], encoding="utf-8"))
    a, b = dict(leaves(old)), dict(leaves(new))
    ins, dele, repl, paths = {}, {}, {}, []
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if x == y:
            continue
        # `meta/` records which source files produced the snapshot (size and mtime), so it always
        # differs when the code itself changes; it is not part of the facts.
        if k.startswith("meta/"):
            continue
        paths.append(k)
        if not isinstance(x, str) or not isinstance(y, str):
            repl[k] = (x, y)
            continue
        sm = difflib.SequenceMatcher(None, x, y, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            if tag in ("insert", "replace"):
                ins[y[j1:j2]] = ins.get(y[j1:j2], 0) + 1
            if tag in ("delete", "replace"):
                dele[x[i1:i2]] = dele.get(x[i1:i2], 0) + 1
            if tag == "replace":
                repl[f"{k} @{i1}"] = (x[i1:i2], y[j1:j2])
    w(f"differing paths: {len(paths)}  (old={sys.argv[1]}, new={sys.argv[2]})")
    for p in paths:
        w(f"  {p}")
    w(f"\ninserted fragments: {ins}")
    w(f"deleted fragments : {dele}")
    w(f"non-string / replace pairs: {list(repl.items())[:10]}")
    ok = (set(ins) == {"洪"} and not dele and not repl)
    w(f"\n[{'PASS' if ok else 'FAIL'}] 唯一的变化是在姓名处插入「洪」")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
