# -*- coding: utf-8 -*-
"""菲利普档：强行纳妾（forced_me_concubine_marriage_opinion）与玩家是否入 opinions 表。

不解析 JSON，直接扫原文。用法：
  & D:\\Roman\\tools\\py.ps1 tools\\diag_philip_opinions.py [melt] [玩家id]
"""
import io
import os
import re
import sys

MELT = sys.argv[1] if len(sys.argv) > 1 else \
    r"D:\Roman\output\菲利普\data\melt_888_01_01.json"
PID = sys.argv[2] if len(sys.argv) > 2 else "38691"
NEEDLES = ["forced_me_concubine_marriage_opinion",
           "concubine_with_monogamous_faith_opinion",
           f'"owner":{PID}', f'"target":{PID}']


def main():
    blob = io.open(MELT, "rb").read()
    print(f"{MELT}  {len(blob):,} 字节")
    for nd in NEEDLES:
        b = nd.encode("utf-8")
        n = blob.count(b)
        print(f"  {nd}: {n} 次")
    # 强行纳妾的 owner/target
    b = NEEDLES[0].encode("utf-8")
    pos = 0
    pairs = []
    while True:
        i = blob.find(b, pos)
        if i < 0:
            break
        ctx = blob[max(0, i - 400):i].decode("utf-8", "replace")
        m = re.findall(r'"owner":(\d+),"target":(\d+)', ctx)
        d = re.findall(r'"start_date":"([\d.]+)"', blob[i:i + 300].
                       decode("utf-8", "replace"))
        pairs.append((m[-1] if m else None, d[:1]))
        pos = i + 1
    print("\nforced 纳妾条目（owner,target / start_date）：")
    for p in pairs:
        print("   ", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
