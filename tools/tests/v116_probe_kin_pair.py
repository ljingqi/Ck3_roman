# -*- coding: utf-8 -*-
"""v116 附带探查（只用缓存）：洪因(177780) 与 洪七公(207044) 之间到底有几条亲缘路线。

用户问：成稿写「同族兄弟」是不是唯一的、最贴切的关系？本探针把两人的共同祖先全部枚举出来
（按 上溯步数和 排序），再列出姻亲侧的联系，供判定。

用法: python -X utf8 tools/tests/v116_probe_kin_pair.py <cidA> <cidB>
"""
import io
import json
import os
import sys
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
CACHE = os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")


def load():
    return json.load(io.open(CACHE, encoding="utf-8"))


def parents(ch, cid):
    fam = (ch.get(str(cid)) or {}).get("family") or {}
    f = [int(x) for x in (fam.get("father") or []) if x is not None]
    m = [int(x) for x in (fam.get("mother") or []) if x is not None]
    return f, m


def name(ch, cid):
    r = ch.get(str(cid)) or {}
    nm = r.get("name_full") or r.get("name_zh") or str(cid)
    b = r.get("birth") or "?"
    d = (r.get("death") or {}).get("date") or ""
    return f"{nm}({cid}, {b}{'–' + d if d else '–alive'})"


def ancs(ch, cid):
    """cid -> (up, all_male) for every ancestor, keeping the shortest route per ancestor."""
    out = {}
    q = deque([(cid, 0, None)])
    seen = set()
    while q:
        cur, up, allm = q.popleft()
        if (cur, up) in seen and up > 0:
            pass
        f, m = parents(ch, cur)
        for p, male in [(x, True) for x in f] + [(x, False) for x in m]:
            am = allm
            if up > 0 or allm is not None:
                am = (True if (allm in (None, True)) else False) and male
            nxt = (p, up + 1, am)
            key = (p, up + 1)
            if key in seen:
                continue
            seen.add(key)
            if p not in out or out[p][0] > up + 1:
                out[p] = (up + 1, am)
            if up + 1 < 6:
                q.append(nxt)
    return out


def main():
    a, b = int(sys.argv[1]), int(sys.argv[2])
    c = load()
    ch = c["characters"]
    print("A =", name(ch, a))
    print("B =", name(ch, b))
    aa, ab = ancs(ch, a), ancs(ch, b)
    rows = []
    for A, (ds, ms) in aa.items():
        if A in ab:
            dc, mc = ab[A]
            if ds == 0 and dc == 0:
                continue
            rows.append((ds + dc, ds, dc, ms, mc, A))
    rows.sort()
    print("\n共同祖先（按 上溯步数和 排序）：")
    for tot, ds, dc, ms, mc, A in rows:
        gen = "同辈" if ds == dc else ("A长一辈" if ds < dc else "B长一辈")
        side = "全父系" if (ms and mc) else ("含母系" if not (ms is True and mc is True) else "?")
        print("  %-28s  A上溯%d  B上溯%d  和=%d  %s  %s"
              % (name(ch, A), ds, dc, tot, gen, side))
    if not rows:
        print("  （六代以内无共同祖先）")
    print("\n姻亲侧：")
    for who, cid in (("A", a), ("B", b)):
        r = ch[str(cid)]
        fam = r.get("family") or {}
        for k in ("spouse", "concubine", "former_spouse", "former_concubine"):
            v = [int(x) for x in (fam.get(k) or [])]
            if v:
                print("  %s.%s = %s" % (who, k, "、".join(name(ch, x) for x in v)))
    # A 的妻子是否与 B 同族/血亲
    fa = (ch[str(a)].get("family") or {})
    fam_b = (ch[str(b)].get("family") or {})
    bs = set(int(x) for x in (fam_b.get("spouse") or []) + (fam_b.get("concubine") or []))
    for w in (fa.get("spouse") or []) + (fa.get("concubine") or []):
        w = int(w)
        aw = ancs(ch, w)
        common = set(aw) & set(ab)
        print("  A 的配偶 %s 与 B 的共同祖先 %d 个%s"
              % (name(ch, w), len(common),
                 ("（含 %s）" % name(ch, sorted(common)[0]) if common else "")))
        if w in bs:
            print("     → 同时是 B 的配偶")
    return 0


if __name__ == "__main__":
    sys.exit(main())
