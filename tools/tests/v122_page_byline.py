# -*- coding: utf-8 -*-
"""Show the byline (life-span line) of one rendered piece in a reading page (v122 check).

Usage: & tools\\py.ps1 tools\\tests\\v122_page_byline.py 田所2 普罗丢色
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
folder = sys.argv[1]
needle = sys.argv[2] if len(sys.argv) > 2 else ""
s = open(os.path.join(ROOT, "output", folder, "index.html"), encoding="utf-8").read()
for m in re.finditer(r'\{"label": "([^"]*)", "meta": "([^"]*)", "html": "(.*?)"\}',
                     s, re.S):
    if needle and needle not in m.group(1):
        continue
    body = m.group(3)
    print("标签:", m.group(1), "| meta:", m.group(2))
    for mm in re.finditer(r'(卒于|死于|去位|转徙无领地|终局)', body):
        seg = body[max(0, mm.start() - 90):mm.end() + 60]
        print("   …" + seg.replace("\\n", " ").replace("\\", "") + "…")
