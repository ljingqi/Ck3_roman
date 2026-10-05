# -*- coding: utf-8 -*-
"""v104 probe: faith/rite tenet layout + ecumenical-council activity traces in a melt.

Byte-scan the melt for the containers we need, then json.loads only those slices:
  * faiths.database[13] (the subject's faith): its rites, its own keys
  * every rite of that faith: tenets / doctrine fingerprints (are they identical?)
  * any activity object of type ecumenical_council (host / location fields)
"""
import hashlib
import json
import sys

MELT = r"D:\Roman\output\洪氏2\data\melt_1077_01_01.json"


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


def load_at(data, key_needle):
    k = data.find(key_needle)
    if k < 0:
        return None, -1
    j = data.find(b":", k)
    j = data.find(b"{", j)
    if j < 0:
        return None, k
    end = slice_value(data, j)
    return json.loads(data[j:end].decode("utf-8")), k


def top_keys(data):
    end = slice_value(data, 0)
    print("total top-level bytes", end, "of", len(data))


def main():
    m = MELT if len(sys.argv) < 2 else sys.argv[1]
    with open(m, "rb") as f:
        data = f.read()
    print("melt", m, len(data))
    top_keys(data)
    # --- faiths / rites
    faiths, _ = load_at(data, b'"faiths"')
    if faiths:
        db = faiths.get("database") or {}
        print("faiths ids sample", sorted(db.keys())[:12], "count", len(db))
        f13 = db.get("13")
        if isinstance(f13, dict):
            print("faith 13 keys", sorted(f13.keys()))
            print("faith 13 rites", json.dumps(f13.get("rites"), ensure_ascii=False)[:400])
            print("faith 13 tenets?", json.dumps(f13.get("tenets"), ensure_ascii=False)[:300])
            print("faith 13 doctrine", json.dumps(f13.get("doctrine"), ensure_ascii=False)[:400])
    rites, _ = load_at(data, b'"rites"')
    if rites:
        rdb = rites.get("database") or {}
        print("rites ids", sorted(rdb.keys(), key=lambda x: int(x))[:40], "count", len(rdb))
        # tenet fingerprints across rites
        fp = {}
        for rid, r in rdb.items():
            d = (r or {}).get("data") or {}
            ten = {}
            for e in (d.get("tenets") or []):
                if isinstance(e, dict) and e.get("tenet"):
                    ten[str(e["tenet"])] = str(e.get("status") or "")
            fh = hashlib.md5(json.dumps(sorted(ten.items()), ensure_ascii=False).encode()).hexdigest()[:10]
            fp.setdefault(fh, []).append((rid, (r or {}).get("faith"), len(ten)))
        for fh, lst in fp.items():
            print("tenet fingerprint", fh, "rites", [(a, b) for a, b, _c in lst][:20])
        for rid in ("154", "185"):
            r = rdb.get(rid)
            if isinstance(r, dict):
                print("rite", rid, "keys", sorted(r.keys()), "faith", r.get("faith"),
                      "head", r.get("head_of_rite"), "founder", r.get("founder"))
    # --- activity traces
    for needle in (b'"ecumenical_council"', b'ecumenical_council',
                   b'"activity_manager"', b'"activities"', b'"activity_type"'):
        c = data.count(needle)
        print("occurrences", needle.decode(), c)
        i = data.find(needle)
        if i >= 0:
            print("   ctx", data[max(0, i - 300):i + 500].decode("utf-8", "replace")[:800])


if __name__ == "__main__":
    main()
