# -*- coding: utf-8 -*-
"""v114 probe: compare one md's whole `### 世系` block with the snapshot's own printed lines."""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.join(ROOT, "output", "洪氏2")
SNAP = os.path.join(BASE, "data", "snap_v114_207044_final.json")


def block(path):
    lines = io.open(path, encoding="utf-8").read().splitlines()
    i = lines.index("### 世系")
    out = []
    for ln in lines[i + 1:]:
        if ln.startswith("### ") or (ln.startswith("#") and not ln.startswith("- ")):
            break
        out.append(ln)
    return out


snap = json.load(io.open(SNAP, encoding="utf-8"))
want = ["- " + ln for ln in snap["facts"]["genealogy"]]
got = block(os.path.join(BASE, "洪七公(1109)_终传_1152_11_13.md"))
print(f"快照行 {len(want)} / 成稿行 {len(got)}")
for i in range(max(len(want), len(got))):
    a = want[i] if i < len(want) else "<无>"
    b = got[i] if i < len(got) else "<无>"
    mark = "  " if a == b else "≠ "
    if a != b:
        print(f"{mark}快照: {a[:150]}")
        print(f"{mark}成稿: {b[:150]}")
print("差异行数:", sum(1 for i in range(max(len(want), len(got)))
                   if (want[i] if i < len(want) else None)
                   != (got[i] if i < len(got) else None)))
print("---- 快照整体 ----")
for ln in want:
    print("   " + ln[:160])
