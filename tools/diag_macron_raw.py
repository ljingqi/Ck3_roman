# -*- coding: utf-8 -*-
"""马克龙（新两问）：熔件原文里搜特质轨道/监狱字段的存法。

不解析 JSON（100MB 解析要 1-3 分钟），直接流式读原文找子串 + 上下文。
用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_macron_raw.py [melt文件名] [关键词...]
"""
import io
import os
import re
import sys

ROOT = r"D:\Roman"
OUT = os.path.join(ROOT, "tools", "out_macron")
MELT = sys.argv[1] if len(sys.argv) > 1 else \
    r"D:\Roman\output\马克龙\data\melt_879_01_01.json"
KEYWORDS = sys.argv[2:] or ["gallowsbait", "trait_xp", "trait_track",
                            "imprisoned", "imprisoner"]


def search(path, kw, before=200, after=700, limit=6):
    lim = os.environ.get("RAW_LIMIT")
    if lim:
        limit = int(lim)
    hits = []
    pat = kw.encode("utf-8")
    with open(path, "rb") as fp:
        blob = fp.read()
    pos = 0
    while len(hits) < limit:
        i = blob.find(pat, pos)
        if i < 0:
            break
        s = max(0, i - before)
        e = min(len(blob), i + after)
        hits.append((i, blob[s:e].decode("utf-8", "replace")))
        pos = i + len(pat)
    return hits, len(blob)


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"读原文 {MELT}", flush=True)
    lines = []
    for kw in KEYWORDS:
        hits, size = search(MELT, kw)
        lines.append(f"===== {kw} : {len(hits)} 处（上限内） =====")
        print(lines[-1], flush=True)
        for i, ctx in hits:
            lines.append(f"--- @{i} ---\n{ctx}")
            print(f"--- @{i} ---\n{ctx}\n", flush=True)
    p = os.path.join(OUT, "raw_search.txt")
    with io.open(p, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    print(f"写入 {p}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
