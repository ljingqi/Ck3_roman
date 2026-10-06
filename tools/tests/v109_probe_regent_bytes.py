# v109 probe: locate regency/diarchy keys inside an existing melt by raw byte scan.
#
# Motivation: loading melt_1155_01_01.json (399 MB) costs minutes; a chunked byte scan
# answers "does this key exist at all, and how often" in seconds. This script never
# mutates any project file except the report it writes under logs/.
#
# Usage: & tools\py.ps1 tools\tests\v109_probe_regent_bytes.py

import mmap
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MELT = os.path.join(ROOT, "output", "洪氏2", "data", "melt_1155_01_01.json")
OUT = os.path.join(ROOT, "logs", "v109_probe_regent_bytes.txt")

# Needles ordered so that narrower spellings are counted independently.
NEEDLES = [
    b'"regency"',
    b'"regency_manager"',
    b'"regencies"',
    b"regency",
    b"regent",
    b"Regent",
    b'"diarchy"',
    b'"diarchies"',
    b'"diarchy_manager"',
    b"diarch",
    b"Diarch",
    b'"co_ruler',
    b'"guardian"',
    b'"court_positions"',
    b'"council_task_manager"',
    b'"scripted_relations"',
    b'"opinion"',
    b'"character_memory_manager"',
    b'"landed_titles"',
    b'"living"',
]

CONTEXT = 220          # bytes either side of a hit
SAMPLES = 3            # how many context samples per needle


def collect(mm, needle, cap=200000):
    """All offsets of `needle` in mm (capped), plus a truncated flag."""
    offs = []
    start = 0
    n = len(needle)
    while True:
        i = mm.find(needle, start)
        if i < 0:
            return offs, False
        offs.append(i)
        if len(offs) >= cap:
            return offs, True
        start = i + 1


def main():
    if not os.path.isfile(MELT):
        print("melt missing: %s" % MELT)
        return 1
    size = os.path.getsize(MELT)
    lines = []
    lines.append("melt = %s" % MELT)
    lines.append("size = %d bytes" % size)
    with open(MELT, "rb") as fp:
        mm = mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for nd in NEEDLES:
                offs, trunc = collect(mm, nd)
                lines.append("")
                lines.append("=" * 78)
                lines.append("needle %-28r hits=%d%s" % (nd, len(offs), " (CAPPED)" if trunc else ""))
                for off in offs[:SAMPLES]:
                    lo = max(0, off - CONTEXT)
                    hi = min(size, off + CONTEXT)
                    snip = mm[lo:hi].decode("utf-8", "replace")
                    lines.append("--- offset %d (context %d..%d) ---" % (off, lo, hi))
                    lines.append(snip)
        finally:
            mm.close()
    text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(text)
    print("wrote %s (%d chars)" % (OUT, len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
