# -*- coding: utf-8 -*-
"""v104 probe: inspect faiths.database entries (does a faith carry its own tenets?) in a melt.

Usage: py tools/tests/v104_probe_faiths.py <melt> [fid ...]
"""
import json
import sys

from v104_probe_melt_activity import stream


def slice_value(data, start):
    depth, i, in_str, esc = 0, start, False, False
    while i < len(data):
        ch = data[i:i + 1]
        if in_str:
            if esc:
                esc = False
            elif ch == b"\\":
                esc = True
            elif ch == b'"':
                in_str = False
        else:
            if ch == b'"':
                in_str = True
            elif ch in (b"{", b"["):
                depth += 1
            elif ch in (b"}", b"]"):
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return len(data)


def main():
    path = sys.argv[1]
    wants = sys.argv[2:]
    needle = b'"faiths":{"database"'
    buf, found = b"", None
    for chunk in stream(path):
        buf += chunk
        p = buf.find(needle)
        if p >= 0:
            j = buf.find(b"{", p + len(needle) - 1)
            end = slice_value(buf, j)
            found = buf[j:end]
            break
        buf = buf[-64:]
    if found is None:
        print("faiths.database not found")
        return
    print("faiths.database bytes", len(found))
    db = json.loads(found.decode("utf-8"))
    print("faith ids", sorted(db.keys(), key=lambda x: int(x))[:40], "count", len(db))
    for fid in (wants or ["13"]):
        e = db.get(fid)
        if not isinstance(e, dict):
            print("faith", fid, "absent")
            continue
        print("=" * 60)
        print("faith", fid, "keys", sorted(e.keys()))
        for k, v in e.items():
            s = json.dumps(v, ensure_ascii=False)
            if k in ("tenets", "doctrine", "rites", "name", "religious_head", "head_of_faith",
                     "variables"):
                print("   ", k, s[:900])
            else:
                print("   ", k, s[:200])


if __name__ == "__main__":
    main()
