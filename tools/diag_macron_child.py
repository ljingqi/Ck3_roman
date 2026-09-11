# -*- coding: utf-8 -*-
"""马克龙档：夭折记忆的母槽覆盖率 + 家室列传事实面里的囚禁取材。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_macron_child.py
"""
import io
import json
import os
import re
import sys

CACHE = r"D:\Roman\output\马克龙\data\player_38677.json"
SNAP = r"D:\Roman\tools\out_macron\snap_38677_878.1.1_d1.json"


def main():
    c = json.load(io.open(CACHE, encoding="utf-8"))
    ch = c["characters"]
    stat = {}
    for cid, r in ch.items():
        for m in r.get("memories") or []:
            t = m.get("type")
            if t not in ("child_stillborn", "child_premature", "child_born",
                         "first_born", "twins_born"):
                continue
            parts = m.get("participants") or {}
            stat.setdefault(t, {"n": 0, "slots": {}, "self_mother": 0})
            stat[t]["n"] += 1
            for k in parts:
                stat[t]["slots"][k] = stat[t]["slots"].get(k, 0) + 1
            if parts.get("mother") is not None and int(parts["mother"]) == int(cid):
                stat[t]["self_mother"] += 1
    print("夭折/出生记忆的参与者槽位分布（缓存内）：")
    print(json.dumps(stat, ensure_ascii=False, indent=1))

    if os.path.exists(SNAP):
        snap = json.load(io.open(SNAP, encoding="utf-8"))
        print("\n快照顶层键:", list(snap.keys())[:20])
        txt = json.dumps(snap, ensure_ascii=False)
        print("快照里含「囚」的片段:")
        for m in re.finditer(r"[^\"\\]{0,60}囚[^\"\\]{0,60}", txt):
            print("   ", m.group(0))
    else:
        print("无快照文件", SNAP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
