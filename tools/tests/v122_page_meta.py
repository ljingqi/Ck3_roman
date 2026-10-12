# -*- coding: utf-8 -*-
"""Print the piece label/meta pairs of a reading page (v122 check).

Usage: & tools\\py.ps1 tools\\tests\\v122_page_meta.py 田所2 [name-substring]
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
folder = sys.argv[1] if len(sys.argv) > 1 else "田所2"
needle = sys.argv[2] if len(sys.argv) > 2 else ""
path = os.path.join(ROOT, "output", folder, "index.html")
s = open(path, encoding="utf-8").read()
pat = re.compile(r'\{"label": "([^"]*)", "meta": "([^"]*)"')
for m in pat.finditer(s):
    if needle and needle not in m.group(1):
        continue
    print(f"{m.group(1)} || {m.group(2)}")
print("死于1119 命中", s.count("死于1119"), "| 御前会议", s.count("御前会议"))
