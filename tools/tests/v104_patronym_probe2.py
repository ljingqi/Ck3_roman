# -*- coding: utf-8 -*-
"""v104 probe 2: family_data father format, culture 271 entry, child records.

Read-only, byte-scan only.
"""
import io
import os
import re
import sys

MELT = r"D:\Roman\output\洪氏2\data\melt_1077_01_01.json"
OUT = r"D:\Roman\logs\v104_patronym_probe2.txt"
CHUNK = 8 * 1024 * 1024

out = io.StringIO()


def p(*a):
    print(*a, file=out)


def window(off, before, after):
    with open(MELT, "rb") as fp:
        fp.seek(max(0, off - before))
        return fp.read(before + after)


def find_all(needle, cap=200):
    res = []
    with open(MELT, "rb") as fp:
        off = 0
        tail = b""
        while True:
            buf = fp.read(CHUNK)
            if not buf:
                break
            data = tail + buf
            base = off - len(tail)
            s = 0
            while True:
                k = data.find(needle, s)
                if k < 0:
                    break
                res.append(base + k)
                if len(res) >= cap:
                    return res
                s = k + 1
            tail = data[-len(needle) - 8:]
            off += len(buf)
    return res


def rec_of(off, starts, offs):
    import bisect
    i = bisect.bisect_right(offs, off) - 1
    return starts[i] if i >= 0 else None


REC_START = re.compile(rb'"(\d{2,10})":\{"')


def record_starts():
    starts = []
    with open(MELT, "rb") as fp:
        off = 0
        tail = b""
        while True:
            buf = fp.read(CHUNK)
            if not buf:
                break
            data = tail + buf
            base = off - len(tail)
            for m in REC_START.finditer(data):
                starts.append((base + m.start(), m.group(1).decode("ascii")))
            tail = data[-64:]
            off += len(buf)
    starts.sort()
    return starts


def main():
    starts = record_starts()
    offs = [s[0] for s in starts]
    byid = {}
    for o, i in starts:
        byid.setdefault(i, []).append(o)
    p("records:", len(starts))

    # 1) father field formats
    p()
    p("=== 1) `\"father\"` occurrence formats ===")
    for needle in (b'"father":135480', b'"father":[135480]', b'"father":135480,',
                   b'"father":', b'"father":[]'):
        hits = find_all(needle, cap=300)
        p(f"  {needle!r}: {len(hits)} hits (cap 300)")
        for h in hits[:4]:
            p("    ctx:", window(h, 120, 120).decode("utf-8", "replace"))

    # 2) how many characters carry culture 271
    p()
    p("=== 2) culture tag counts ===")
    for c in (271, 161, 75, 265, 76, 163):
        n = len(find_all(b'"culture":%d,' % c, cap=100000))
        p(f'  "culture":{c}, -> {n}')
    for c in (271, 161, 75, 265):
        n = len(find_all(b'"culture":%d}' % c, cap=100000))
        p(f'  "culture":{c}}} -> {n}')

    # 3) culture_manager culture 271
    p()
    p("=== 3) culture_manager culture 271 ===")
    cm = find_all(b'"culture_manager"', cap=5)
    p("  culture_manager at", cm)
    for base in cm:
        blob = window(base, 0, 40_000_000)
        j = blob.find(b'"271":{')
        if j < 0:
            p("    271 not within 40MB window")
            continue
        p("    absolute offset", base + j)
        p("    " + blob[j:j + 1500].decode("utf-8", "replace"))
        break

    # 4) child records
    p()
    p("=== 4) child records of 135480 ===")
    kids = [117484775, 83995743, 33706092, 50481660, 100805893, 100806807,
            83993097, 16917443, 165998, 134308845, 166714, 166715, 167488,
            170120, 16945142, 172268]
    for k in kids:
        cand = byid.get(str(k), [])
        if not cand:
            p(f"  {k}: no record in this melt")
            continue
        head = window(cand[0], 0, 1200).decode("utf-8", "replace")
        p(f"  --- {k} @ {cand[0]} ---")
        p("   " + head)

    # 5) the protagonist record, deeper
    p()
    p("=== 5) protagonist 135480 record, windows ===")
    o = byid["135480"][0]
    blob = window(o, 0, 12000).decode("utf-8", "replace")
    for key in ('"culture"', '"faith"', '"dead_data"', '"family_data"'):
        i = blob.find(key)
        p(f"  {key} at +{i}")
    p("  --- 6000..9000 ---")
    p("  " + blob[6000:9000])
    return 0


if __name__ == "__main__":
    main()
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(out.getvalue())
    sys.stderr.write(f"written {OUT}\n")
