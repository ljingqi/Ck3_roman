# -*- coding: utf-8 -*-
"""v111 探查：逐年份读熔件封套里的 meta_data（存档列表上游戏自己写的主衔显示名）。

`meta_data.meta_title_name` 是游戏写进存档封套的「玩家主头衔」名，等于游戏界面上的显示名；
它就在 JSON 最前面，所以只需流式解压头几百 KB。

用法：
    & tools\\py.ps1 tools\\tests\\v111_probe_meta_title.py <folder> [<years>]
"""
import json
import lzma
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KEYS = ("meta_title_name", "meta_player_name", "meta_date", "meta_player_id",
        "meta_title_id", "meta_title_key")


def _meta(path):
    with lzma.open(path, "rb") if path.endswith(".xz") else open(path, "rb") as fp:
        s = fp.read(400000).decode("utf-8", "replace")
    m = re.search(r'"meta_data"\s*:\s*\{', s)
    if not m:
        return None
    i = m.end() - 1
    depth, q, esc, j = 0, False, False, i
    while j < len(s):
        c = s[j]
        if q:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                q = False
        elif c == '"':
            q = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    try:
        return json.loads(s[i:j + 1])
    except ValueError:
        return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    folder = sys.argv[1]
    data = os.path.join(ROOT, "output", folder, "data")
    want = set(sys.argv[2:])
    names = sorted(x for x in os.listdir(data)
                   if x.startswith("melt_") and "_idx" not in x)
    for fn in names:
        y = fn.split("_")[1]
        if want and y not in want:
            continue
        md = _meta(os.path.join(data, fn))
        if md is None:
            print("%s  meta_data 未在前 400KB 内" % fn)
            continue
        print("%s  %s" % (fn, {k: md.get(k) for k in KEYS if k in md}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
