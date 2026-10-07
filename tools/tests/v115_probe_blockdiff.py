# -*- coding: utf-8 -*-
"""v115 probe (snapshot + md only): which appendix 世系 lines are per-file, and the block shape."""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.join(ROOT, "output", "洪氏2")
SNAP = os.path.join(BASE, "data", "snap_v114_207044_final.json")
facts = json.load(io.open(SNAP, encoding="utf-8"))["facts"]
want = ["- " + ln for ln in (facts.get("genealogy") or [])]
print(f"snapshot 世系 lines: {len(want)}")


def block(lines):
    i = lines.index("### 世系")
    j = i + 1
    while j < len(lines) and not lines[j].startswith("#"):
        j += 1
    return lines[i + 1:j]


for fn in sorted(os.listdir(BASE)):
    if not fn.endswith(".md"):
        continue
    with io.open(os.path.join(BASE, fn), encoding="utf-8") as fp:
        lines = fp.read().splitlines()
    if "### 世系" not in lines:
        continue
    b = block(lines)
    tail = b[len(want):] if len(b) >= len(want) else []
    same = b[:len(want)] == want
    print(f"\n{fn}: 块 {len(b)} 行, 前 {len(want)} 行与快照"
          f"{'一致' if same else '不一致'}, 额外行 {len(tail)}")
    for x in tail:
        print("    extra:", repr(x))
    if not same:
        for k in range(min(len(b), len(want))):
            if b[k] != want[k]:
                print("    diff@", k)
                print("      md  :", repr(b[k][:120]))
                print("      snap:", repr(want[k][:120]))
                break
    empt = [k for k, x in enumerate(b) if not x.strip()]
    print("    空行位置:", empt, " 末尾两行:", [x[:40] for x in b[-2:]])
    if re.search(r"^\s*$", "\n".join(b)):
        pass
