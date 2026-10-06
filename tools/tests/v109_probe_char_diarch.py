# v109 probe: shape of the character-side diarchy fields, by raw byte scan of an existing melt.
#
# Answers "does the diarch's own character block point back at the diarchy, or is the link
# one-directional in `diarchies.database`?" without loading the 399 MB melt. Read-only.
#
# Usage: & tools\py.ps1 tools\tests\v109_probe_char_diarch.py

import mmap
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MELT = os.path.join(ROOT, "output", "洪氏2", "data", "melt_1155_01_01.json")
OUT = os.path.join(ROOT, "logs", "v109_probe_char_diarch.txt")

LIEGE = b'33725392'      # 洪大力
DIARCH = b'67210684'     # 洪卡特琳

WINDOW = 9000

# Candidate reverse-pointer / related field names worth confirming absent or present.
CANDIDATES = [
    b'"diarchy_of"', b'"diarch_of"', b'"regent_of"', b'"my_diarchy"',
    b'"regency_of"', b'"is_diarch"', b'"diarchies":', b'"diarchy":',
    b'"guardian"', b'"guardian_of"', b'"ward"', b'"hostage"',
    b'"council_task"', b'"court_positions"', b'"playable_data"',
]


def main():
    if not os.path.isfile(MELT):
        print("melt missing")
        return 1
    lines = []
    with open(MELT, "rb") as fp:
        mm = mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for label, cid in (("liege 洪大力", LIEGE), ("diarch 洪卡特琳", DIARCH)):
                pat = b'"' + cid + b'":{"first_name"'
                hits = []
                start = 0
                while True:
                    i = mm.find(pat, start)
                    if i < 0:
                        break
                    hits.append(i)
                    start = i + 1
                lines.append("=" * 78)
                lines.append("%s  cid=%s  block-start hits=%d at %r"
                             % (label, cid.decode(), len(hits), hits[:10]))
                for off in hits[:2]:
                    seg = mm[off:off + WINDOW]
                    lines.append("--- raw %d bytes from offset %d ---" % (WINDOW, off))
                    lines.append(seg.decode("utf-8", "replace"))
                    lines.append("--- 'diarch' occurrences inside this window ---")
                    s = 0
                    while True:
                        j = seg.find(b"diarch", s)
                        if j < 0:
                            break
                        lines.append("  +%d: %s" % (j, seg[max(0, j - 60):j + 90]
                                                    .decode("utf-8", "replace")))
                        s = j + 1
                lines.append("")
            lines.append("=" * 78)
            lines.append("candidate field-name byte counts in the whole melt")
            for nd in CANDIDATES:
                n = 0
                s = 0
                while True:
                    j = mm.find(nd, s)
                    if j < 0:
                        break
                    n += 1
                    s = j + 1
                    if n > 100000:
                        break
                lines.append("  %-22s %d" % (nd.decode(), n))
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
