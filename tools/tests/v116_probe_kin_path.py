# -*- coding: utf-8 -*-
"""v116 附带探查 3（只用缓存）：打印两人各自到共同祖先 洪天贵福 的上溯链。"""
import io
import json
import os
import sys
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
CACHE = os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")


def main():
    a, b, target = (int(x) for x in sys.argv[1:4])
    cache = json.load(io.open(CACHE, encoding="utf-8"))
    ch = cache["characters"]

    def nm(cid):
        r = ch.get(str(cid)) or {}
        return "%s(%s)" % (r.get("name_full") or r.get("name_zh") or "?", cid)

    def links(cid):
        f = (ch.get(str(cid)) or {}).get("family") or {}
        out = [("父", x) for x in (f.get("father") or []) if isinstance(x, int)]
        out += [("生父", x) for x in (f.get("real_father") or []) if isinstance(x, int)]
        out += [("母", x) for x in (f.get("mother") or []) if isinstance(x, int)]
        return out

    for tag, src in (("A", a), ("B", b)):
        prev = {src: None}
        q = deque([src])
        while q:
            cur = q.popleft()
            if cur == target:
                break
            for kind, p in links(cur):
                if p not in prev:
                    prev[p] = (cur, kind)
                    q.append(p)
        if target not in prev:
            print("%s 未能到 %s" % (tag, nm(target)))
            continue
        chain = []
        cur = target
        while prev[cur] is not None:
            parent, kind = prev[cur]
            chain.append((kind, parent))
            cur = parent
        print("%s = %s 上溯到 %s：" % (tag, nm(src), nm(target)))
        for kind, cid in chain:
            print("    %s → %s" % (kind, nm(cid)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
