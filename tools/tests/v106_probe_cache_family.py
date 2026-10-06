# -*- coding: utf-8 -*-
"""v106 probe: stream the built cache and print the protagonist's own record head.

Question: at the death snapshot, does `characters["<pid>"]["family"]` still carry the spouse /
child lists that `biography._fix_kin_roles` reads (raw, un-latched)? Streamed in 4MB chunks so the
121MB cache is never fully loaded.
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "output", "洪氏2", "data", "player_117484775.json")
OUT = os.path.join(ROOT, "logs", "v106_cache_family.txt")

needle = b'"117484775":{'
CHUNK = 4 << 20
tail = b""
hits = []
with io.open(SRC, "rb") as fp:
    off = 0
    while True:
        buf = fp.read(CHUNK)
        if not buf:
            break
        data = tail + buf
        i = data.find(needle)
        if i != -1:
            hits.append((off - len(tail) + i, data[i:i + 40000]))
            if len(hits) >= 6:
                break
        tail = data[-len(needle):]
        off += len(buf)

lines = ["file=%s size=%d hits=%d" % (SRC, os.path.getsize(SRC), len(hits)), ""]
for pos, blob in hits:
    lines.append("---- offset %d ----" % pos)
    lines.append(blob.decode("utf-8", "replace"))
    lines.append("")
io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
sys.stdout.write("wrote %s (%d hits)\n" % (OUT, len(hits)))
