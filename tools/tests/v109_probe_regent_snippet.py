# v109 probe: raw JSON snippet of the sample regency record inside the plain melt.
#
# Produces the exact bytes for the report (id 2583691663: liege 33725392 洪大力, diarch
# 67210684 洪卡特琳), plus the section opening. Byte scan only; no json.load. Read-only.
#
# Usage: & tools\py.ps1 tools\tests\v109_probe_regent_snippet.py

import mmap
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MELT = os.path.join(ROOT, "output", "洪氏2", "data", "melt_1155_01_01.json")
OUT = os.path.join(ROOT, "logs", "v109_probe_regent_snippet.txt")

NEEDLES = [
    b'"diarchies":{"database":',
    b'"2583691663":{"liege":33725392',
    b'"playable_data":{"diarchy":2583691663',
]


def main():
    lines = []
    size = os.path.getsize(MELT)
    lines.append("melt = %s (%d bytes)" % (MELT, size))
    with open(MELT, "rb") as fp:
        mm = mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for nd in NEEDLES:
                i = mm.find(nd)
                lines.append("")
                lines.append("=" * 78)
                if i < 0:
                    lines.append("needle %r NOT FOUND" % nd)
                    continue
                lo = max(0, i - 200)
                hi = min(size, i + 700)
                lines.append("needle %r at offset %d" % (nd, i))
                lines.append("--- bytes %d..%d ---" % (lo, hi))
                lines.append(mm[lo:hi].decode("utf-8", "replace"))
        finally:
            mm.close()
    text = "\n".join(lines) + "\n"
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
