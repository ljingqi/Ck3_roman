# -*- coding: utf-8 -*-
"""v113 probe: the dynasty words on the princess/prince labels in the new snapshot (no melt)."""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
PAIRS = [("snap_v112_207044_final.json", "v112"), ("snap_v113_207044_final.json", "v113")]
PAT = re.compile(r"(唐|天|邓|大邓|大唐)[皇公]?(女|主|王子|公主)")
NAME = re.compile(r"[唐天邓大]{0,2}[皇公]?[女主王子]{0,2}(李星雁|洪天姣|李漼)")
WORD = re.compile(r"(唐公主|天公主|邓公主|大邓皇女|大唐皇女|唐皇女|天皇后|唐王子|邓王子|唐皇帝)")


def dump(name):
    p = os.path.join(ROOT, "output", "洪氏2", "data", name)
    snap = json.load(io.open(p, encoding="utf-8"))
    blob = json.dumps(snap.get("facts") or {}, ensure_ascii=False)
    counts = {}
    for m in WORD.finditer(blob):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    print(name)
    for w in ("唐公主", "天公主", "邓公主", "大邓皇女", "大唐皇女", "唐王子", "邓王子", "唐皇帝"):
        if counts.get(w):
            print(f"    {w}: {counts[w]}")
    for who in ("李星雁", "洪天姣", "李漼"):
        for m in re.finditer(r"[\u4e00-\u9fff·，、：]{0,6}" + who, blob):
            print(f"    {who}: {m.group(0)}")


for fn, tag in PAIRS:
    dump(fn)
