# -*- coding: utf-8 -*-
"""v104 probe: byte-scan a CK3 melt for character name fields.

Read-only. Never json.loads the melt. Answers:
  - what a character record stores for a name (first_name / name / patronym...);
  - whether the patronymic the game shows exists anywhere in the save text;
  - which name_list a hybrid culture carries.

Usage:
  & tools\\py.ps1 tools\\tests\\v104_patronym_probe.py > logs\\v104_patronym_probe.txt
"""
import bisect
import io
import os
import re
import sys

MELT = r"D:\Roman\output\洪氏2\data\melt_1077_01_01.json"
OUT = r"D:\Roman\logs\v104_patronym_probe.txt"
CHUNK = 8 * 1024 * 1024
OVERLAP = 64

REC_START = re.compile(rb'"(\d{2,10})":\{"')

out = io.StringIO()


def p(*a):
    print(*a, file=out)


def record_starts(path):
    """[(byte offset, id string)] for every `"<id>":{"` occurrence."""
    starts = []
    with open(path, "rb") as fp:
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
            tail = data[-OVERLAP:]
            off += len(buf)
    starts.sort()
    return starts


def window(path, off, before, after):
    with open(path, "rb") as fp:
        fp.seek(max(0, off - before))
        return fp.read(before + after)


def count_bytes(path, needles):
    """Exact byte-occurrence counts for each needle, streaming."""
    counts = {n: 0 for n in needles}
    with open(path, "rb") as fp:
        tail = b""
        while True:
            buf = fp.read(CHUNK)
            if not buf:
                break
            data = tail + buf
            for n in needles:
                start = 0
                while True:
                    i = data.find(n, start)
                    if i < 0:
                        break
                    counts[n] += 1
                    start = i + 1
            tail = data[-32:]
    return counts


def first_name_at(path, off):
    w = window(path, off, 0, 400)
    m = re.search(rb'"first_name":"((?:[^"\\]|\\.)*)"', w)
    if not m:
        return None
    return m.group(1).decode("utf-8", "replace")


def main():
    if not os.path.exists(MELT):
        p("MISSING", MELT)
        return 1
    p("melt:", MELT, os.path.getsize(MELT), "bytes")
    starts = record_starts(MELT)
    p("record-start `\"<id>\":{\"` occurrences:", len(starts))
    offs = [s[0] for s in starts]

    def rec_of(off):
        i = bisect.bisect_right(offs, off) - 1
        return starts[i] if i >= 0 else None

    # ------------------------------------------------------------------
    # 1) global counts of patronymic-looking text and of name fields
    # ------------------------------------------------------------------
    p()
    p("=== 1) byte counts ===")
    needles = [
        b'"first_name":"',
        b'"patronym',
        b'"family_data"',
        b'"dynasty_house"',
        b'"nickname',
        b'\xe6\x89\x98\xe5\x88\xa9\xe5\xb0\x94\xe6\x9d\xbe',   # 托利尔松
        b'\xe6\x9d\xbe',                                        # 松
        b'\xe6\x96\xaf\xe5\xa4\x9a\xe8\x92\x82\xe5\xb0\x94',   # 斯多蒂尔
        b'\xe5\xa4\x9a\xe7\x89\xb9',                            # 多特
        b'\xe8\x80\x80\xe5\x9b\xbd',                            # 耀国
        b'\xe6\xb4\xaa\xe5\xa0\xa1',                            # 洪堡
        b'\xe5\xb8\x8c\xe6\x9f\x8f\xe8\x80\xb3\xe5\xb0\xbc\xe4\xba\x9a',  # 希柏耳尼亚
    ]
    for n, c in count_bytes(MELT, needles).items():
        p(f"  {n!r:60s} {c}")

    # ------------------------------------------------------------------
    # 2) culture 271 entry (name_list / name_order_convention / template)
    # ------------------------------------------------------------------
    p()
    p("=== 2) culture 271 entry ===")
    with open(MELT, "rb") as fp:
        data = fp.read()
    i = data.find('"271":{"name"'.encode("utf-8"))
    if i < 0:
        i = data.find('culture_manager'.encode("utf-8"))
        p("  `\"271\":{\"name\"` not found; culture_manager at", i)
        j = data.find(b'"271":{', i)
        i = j
    p("  offset", i)
    p("  " + data[max(0, i - 60):i + 1400].decode("utf-8", "replace"))
    del data

    # ------------------------------------------------------------------
    # 3) the protagonist and his sons
    # ------------------------------------------------------------------
    p()
    p("=== 3) characters whose family_data.father is 135480 ===")
    pat = b'"father":135480'
    hits = []
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
                k = data.find(pat, s)
                if k < 0:
                    break
                hits.append(base + k)
                s = k + 1
            tail = data[-32:]
            off += len(buf)
    p("  occurrences of", pat, len(hits))
    for h in hits:
        r = rec_of(h)
        p(f"  hit@{h} -> record {r[0]} id={r[1]} first_name={first_name_at(MELT, r[0])!r}")

    # ------------------------------------------------------------------
    # 4) full head of every son record + the protagonist record
    # ------------------------------------------------------------------
    p()
    p("=== 4) record heads ===")
    ids = sorted({rec_of(h)[1] for h in hits if rec_of(h)} | {"135480"})
    for cid in ids:
        cand = [s for s in starts if s[1] == cid]
        p()
        p(f"--- id {cid} ({len(cand)} record(s)) ---")
        for off, _ in cand[:2]:
            p(f"  offset {off}")
            p("  " + window(MELT, off, 0, 2600).decode("utf-8", "replace"))

    # ------------------------------------------------------------------
    # 5) the named courtiers/profiles the user cited
    # ------------------------------------------------------------------
    p()
    p("=== 5) cited patronymic-bearing characters ===")
    for label, needle in [
        ("伊瓦尔", "伊瓦尔".encode("utf-8")),
        ("托利尔松", "托利尔松".encode("utf-8")),
        ("因德雷赫塔赫", "因德雷赫塔赫".encode("utf-8")),
        ("海内什", "海内什".encode("utf-8")),
        ("纽尔古", "纽尔古".encode("utf-8")),
    ]:
        offs_hit = []
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
                    offs_hit.append(base + k)
                    s = k + 1
                tail = data[-32:]
                off += len(buf)
        p()
        p(f"--- {label}: {len(offs_hit)} byte hits ---")
        for h in offs_hit[:6]:
            r = rec_of(h)
            p(f"  hit@{h} ctx={window(MELT, h, 90, 90).decode('utf-8','replace')!r}")
            if r:
                p(f"    -> record id={r[1]} first_name={first_name_at(MELT, r[0])!r}")
                p("    " + window(MELT, r[0], 0, 900).decode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    rc = main()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(out.getvalue())
    sys.stderr.write(f"written {OUT}\n")
    sys.exit(rc)
