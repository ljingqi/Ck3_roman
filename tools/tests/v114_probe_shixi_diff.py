# -*- coding: utf-8 -*-
"""v114 probe: diff the odd 世系 blocks against the common one."""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.join(ROOT, "output", "洪氏2")
COMMON = "洪七公(1109)_终传_1152_11_13.md"
ODD = ["洪易卜拉欣(1059)_终传_1126_07_30.md", "缯·洪堡(954)_终传_1009_06_26.md"]


def block(fn):
    txt = io.open(os.path.join(BASE, fn), encoding="utf-8").read().splitlines()
    i = txt.index("### 世系")
    out = []
    for ln in txt[i + 1:]:
        if ln.startswith("### ") or (ln.startswith("#") and not ln.startswith("- ")):
            break
        out.append(ln)
    return out


ref = block(COMMON)
for fn in ODD:
    b = block(fn)
    print("==", fn)
    for i in range(max(len(ref), len(b))):
        a = ref[i] if i < len(ref) else "<无>"
        c = b[i] if i < len(b) else "<无>"
        if a != c:
            print("   ref:", a[:150])
            print("   odd:", c[:150])
