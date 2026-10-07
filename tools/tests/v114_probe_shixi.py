# -*- coding: utf-8 -*-
"""v114 probe: compare every md's `### 世系` block and its head lines."""
import hashlib
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.join(ROOT, "output", "洪氏2")


def block(txt):
    lines = txt.splitlines()
    try:
        i = lines.index("### 世系")
    except ValueError:
        return None
    out = []
    for ln in lines[i + 1:]:
        if ln.startswith("### ") or (ln.startswith("#") and not ln.startswith("- ")):
            break
        out.append(ln)
    return out


for fn in sorted(os.listdir(BASE)):
    if not fn.endswith(".md"):
        continue
    txt = io.open(os.path.join(BASE, fn), encoding="utf-8").read()
    b = block(txt)
    if b is None:
        continue
    heads = [ln for ln in b if ln.startswith("- **")]
    h = hashlib.sha1("\n".join(b).encode("utf-8")).hexdigest()[:10]
    print(f"{fn:44s} 行 {len(b):3d} 头 {len(heads)} sha {h}")
