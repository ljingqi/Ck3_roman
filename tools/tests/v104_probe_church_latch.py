# -*- coding: utf-8 -*-
"""v104 probe: extract the church-history latches from the 洪氏2 cache by bracket matching.

Prints, per latch id: the latch dates and the diff between consecutive latches, so the
ruling windows (and which rite ids are latched at all) are visible without loading 244MB.
"""
import json

PATH = r"D:\Roman\output\洪氏2\data\player_135480.json"
KEYS = ["rite_tenets_history", "rite_doctrine_history", "faith_doctrine_history"]


def extract(data, key):
    needle = ('"%s":' % key).encode("utf-8")
    i = data.find(needle)
    if i < 0:
        return None
    j = i + len(needle)
    depth = 0
    k = j
    while k < len(data):
        ch = data[k:k + 1]
        if ch == b"{":
            depth += 1
        elif ch == b"}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    return json.loads(data[j:k + 1].decode("utf-8"))


def main():
    with open(PATH, "rb") as f:
        data = f.read()
    out = {}
    for key in KEYS:
        blk = extract(data, key)
        print("=" * 78)
        print(key, "ids:", sorted(blk.keys()) if blk else None)
        for pid, rows in (blk or {}).items():
            print("-- id", pid, "latches", len(rows))
            for n, r in enumerate(rows):
                print("   ", n, r.get("from"), r.get("head"))
            if key.endswith("tenets_history") and len(rows) > 1:
                for n in range(1, len(rows)):
                    a = {t: s for s, ts in (rows[n - 1]["tenets"] or {}).items() for t in ts}
                    b = {t: s for s, ts in (rows[n]["tenets"] or {}).items() for t in ts}
                    ch = {t: (a.get(t), b.get(t)) for t in set(a) | set(b) if a.get(t) != b.get(t)}
                    if ch:
                        print("    diff", rows[n]["from"], ch)
            if "doctrine" in key and len(rows) > 1:
                for n in range(1, len(rows)):
                    a = set(rows[n - 1]["doctrines"])
                    b = set(rows[n]["doctrines"])
                    if a != b:
                        print("    diff", rows[n]["from"], "OUT", sorted(a - b), "IN", sorted(b - a))
        out[key] = blk
    return out


if __name__ == "__main__":
    main()
