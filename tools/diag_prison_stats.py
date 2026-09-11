# -*- coding: utf-8 -*-
"""对比两份快照的时间线监禁/夭折事件与概览统计（问题1 复核）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_prison_stats.py <快照A> [快照B]
"""
import io
import json
import sys


def dump(path):
    s = json.load(io.open(path, encoding="utf-8"))
    tl = (s.get("facts") or {}).get("timeline") or []
    print(f"===== {path}")
    print("  概览:", (s.get("facts") or {}).get("decade_stats"))
    for e in tl:
        if e.get("type") in ("imprisoned", "imprisoned_other", "escaped_from_prison_memory",
                             "released_from_prison_memory", "child_stillborn",
                             "child_premature") or "囚" in (e.get("text") or ""):
            print(f"   [{e.get('type')}/{e.get('module')}] {e.get('text')}")


for p in sys.argv[1:]:
    dump(p)
