# -*- coding: utf-8 -*-
"""Each reading page: does it parse, does it carry a tree, and how many tree hosts are inlined?"""
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
for p in sorted(glob.glob(os.path.join(ROOT, "output", "*", "index.html"))):
    html = io.open(p, encoding="utf-8").read()
    m = re.search(r"const DATA = (\{.*?\});\nconst CHARS", html, re.S)
    ok, roles, tree = "无数据段", 0, "-"
    if m:
        try:
            d = json.loads(m.group(1))
            ok, roles = "ok", len(d.get("chars") or [])
            tree = "有" if d.get("tree") else "无"
        except Exception as e:
            ok = str(e)[:36]
    print("%-34s %-6s 角色 %d 家谱 %s 内嵌容器 %d 家谱按钮 %s"
          % (os.path.relpath(p, ROOT), ok, roles, tree,
             len(re.findall(r'class="tree-host"', html)),
             "yes" if 'id="tree-btn"' in html else "no"))
