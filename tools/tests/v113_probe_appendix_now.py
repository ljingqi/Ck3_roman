# -*- coding: utf-8 -*-
"""Show the appendix section each 终传 currently carries (before/after a migration step)."""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
base = os.path.join(ROOT, "output", "洪氏2")
SEC = re.compile(r"^### (世系|家谱)\s*$(.*?)(?=^#{2,3} |\Z)", re.M | re.S)
for fn in sorted(os.listdir(base)):
    if not fn.endswith(".md") or "终传" not in fn:
        continue
    text = io.open(os.path.join(base, fn), encoding="utf-8").read()
    m = SEC.search(text)
    if not m:
        print("==", fn, "（无附录段）")
        continue
    body = m.group(2).strip("\n").splitlines()
    grid = [ln for ln in body if "家格" in ln]
    print("== %-44s ### %s  行 %d  家格 %d" % (fn, m.group(1), len(body), len(grid)))
    for ln in body[:4]:
        print("     ", ln[:70])
    if len(body) > 4:
        print("      …", body[-1][:70])
