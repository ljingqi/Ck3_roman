# -*- coding: utf-8 -*-
"""读 facts 快照：看家室列传/本纪的囚禁与夭折事实面（问题1/3）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_snap_probe.py [快照路径] [关键词...]
"""
import io
import json
import os
import re
import sys

SNAP = sys.argv[1] if len(sys.argv) > 1 else \
    r"D:\Roman\output\马克龙\data\snap_38677_878.1.1_d1.json"
KEYS = sys.argv[2:] or ["囚", "夭折", "妾"]


def main():
    s = json.load(io.open(SNAP, encoding="utf-8"))
    print("顶层:", list(s.keys()))
    print("meta:", json.dumps(s.get("meta"), ensure_ascii=False)[:400])
    print("\nblocks 键:", list(s.get("blocks") or {}))
    for name, blk in (s.get("blocks") or {}).items():
        txt = blk if isinstance(blk, str) else json.dumps(blk, ensure_ascii=False)
        print(f"  {name}: {len(txt)} 字符")
    print("\n==== 共享前缀里的关键词 ====")
    shared = s.get("shared") or ""
    for k in KEYS:
        for m in re.finditer(r"[^\n]{0,70}" + re.escape(k) + r"[^\n]{0,70}", shared):
            print(f"  [{k}] {m.group(0)}")
    print("\n==== 各板块块内的关键词 ====")
    for name, blk in (s.get("blocks") or {}).items():
        txt = blk if isinstance(blk, str) else json.dumps(blk, ensure_ascii=False)
        for k in KEYS:
            for m in re.finditer(r"[^\n]{0,70}" + re.escape(k) + r"[^\n]{0,70}", txt):
                print(f"  {name} [{k}] {m.group(0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
