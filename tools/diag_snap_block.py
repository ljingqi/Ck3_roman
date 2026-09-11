# -*- coding: utf-8 -*-
"""打印快照里某一板块的原文（供方案引用证据）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_snap_block.py jiashi_lead jiashi_mid
"""
import io
import json
import sys

SNAP = r"D:\Roman\output\马克龙\data\snap_38677_878.1.1_d1.json"


def main():
    s = json.load(io.open(SNAP, encoding="utf-8"))
    want = sys.argv[1:] or ["jiashi_lead"]
    for k in want:
        blk = s["blocks"].get(k)
        print(f"================ {k} ================")
        if blk is None:
            print("（无此块）")
            continue
        print(blk if isinstance(blk, str)
              else json.dumps(blk, ensure_ascii=False, indent=1))
        print()
    if "--user" in want:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
