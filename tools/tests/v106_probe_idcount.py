# -*- coding: utf-8 -*-
"""v106 probe: count raw occurrences of a few ids in the built cache (streamed)."""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "output", "洪氏2", "data", "player_117484775.json")
IDS = ["172268", "154984", "16917443", "165998", "174036", "135480", "16895643",
       "117484775"]

counts = {i: 0 for i in IDS}
shapes = {i: [] for i in IDS}
CHUNK = 8 << 20
tail = ""
with io.open(SRC, "r", encoding="utf-8", errors="replace") as fp:
    while True:
        buf = fp.read(CHUNK)
        if not buf:
            break
        data = tail + buf
        for i in IDS:
            n = data.count(i)
            counts[i] += n
            if n:
                j = data.find(i)
                shapes[i].append(data[max(0, j - 20):j + 24].replace("\n", " "))
        tail = data[-32:]
for i in IDS:
    print("%-12s %6d   %s" % (i, counts[i], shapes[i][:2]))
