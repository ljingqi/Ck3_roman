# -*- coding: utf-8 -*-
"""v119 probe: how many people the clan really holds, against the 203 beads of data/genealogy.json.

The reading page's 家谱 is built by `facts.genealogy_tree`, whose scope is the printed 世系's scope
(the played chain plus one step of kin per generation). This probe measures that scope against the
whole recorded clan in the same cache, so the gap is a number, not a guess.

Nothing is rewritten: the probe only reads the cache and the tree sidecar.

Usage:  python tools/tests/v119_probe_clan.py [家族文件夹]
"""
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import cache_lib as cl                                     # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "洪氏2"
DATA = os.path.join(ROOT, "output", FOLDER, "data")
sys.setrecursionlimit(200000)


def main():
    tree = json.load(open(os.path.join(DATA, "genealogy.json"), encoding="utf-8"))
    nodes = tree.get("nodes") or []
    tree_ids = {n["id"] for n in nodes}
    pid = tree.get("player_id")
    print(f"家谱数据: 珠 {len(nodes)} 人 · 传主 {len(tree.get('chain') or [])} 位"
          f" · 基准 {tree.get('as_of')} · 基准人物 {pid}")

    name = f"player_{pid}.json"
    path = os.path.join(DATA, name)
    print(f"缓存 {name}: {os.path.getsize(path) / 1048576:.1f} MB")
    cache = json.load(open(path, encoding="utf-8"))
    chars = cache.get("characters") or {}
    as_of = cache.get("last_date")
    dname = cache.get("dynasty_name")
    print(f"缓存：人物 {len(chars)} 人 · 宗族「{dname}」 · last_date {as_of}")

    def alive(cid):
        rec = chars.get(str(cid)) or {}
        b = str(rec.get("birth") or "")
        if b and as_of and cl.date_key(b) > cl.date_key(as_of):
            return False
        d = rec.get("death")
        d = (d or {}).get("date") if isinstance(d, dict) else d
        return not (d and as_of and cl.date_key(str(d)) <= cl.date_key(as_of))

    # the clan = every house carrying the same dynasty name (分家 included; the cache stores the name
    # per character, so this needs no melt)
    clan = [int(k) for k in chars if str(k).isdigit()
            and (chars[str(k)] or {}).get("dynasty_name") == dname]
    clan_set = set(clan)
    alive_n = [c for c in clan if alive(c)]
    print(f"同宗「{dname}」共 {len(clan)} 人：在世 {len(alive_n)} · 已故 {len(clan) - len(alive_n)}")
    print(f"  已在家谱图上 {len(clan_set & tree_ids)} 人 · 图外 {len(clan_set - tree_ids)} 人")
    houses = Counter(str((chars.get(str(c)) or {}).get("house_name") or "") for c in clan)
    print(f"  分家（房名）分布 top8: {houses.most_common(8)}")
    foreign = [c for c in tree_ids if str(c) not in chars
               or (chars[str(c)] or {}).get("dynasty_name") != dname]
    print(f"  图上非同宗（婚入等）{len(foreign)} 人")

    # blood descent from the clan's first recorded member, following father/mother links
    root = (tree.get("chain") or [{}])[0].get("id")
    kids = {}
    for cid in clan:
        fam = (chars.get(str(cid)) or {}).get("family") or {}
        for p in list(fam.get("father") or []) + list(fam.get("mother") or []):
            if isinstance(p, int):
                kids.setdefault(p, []).append(cid)
    seen, depth, stack = set(), {root: 0}, [root] if root else []
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        for k in kids.get(x, []):
            depth.setdefault(k, depth[x] + 1)
            stack.append(k)
    back = {c for c in clan if c not in seen}
    print(f"从始祖 {root} 沿父母血亲可及的后裔 {len(seen)} 人；宗族内另有 {len(back)} 人接不上"
          f"（婚入、或缓存未存其父母）")
    wid = Counter(depth.values())
    print("  血亲世代分布：" + " ".join(f"{g}代{wid[g]}人" for g in sorted(wid)))
    if wid:
        beast = max(wid.values())
        print(f"  最宽一代 {beast} 人 —— 一行一个世代时该行约 {beast * 152}px（152px/珠 @13px，"
              f"现图 6202px）")

    # what a clan-wide chart would have to draw: adding the spouses the same records carry
    sp = set()
    for cid in clan:
        fam = (chars.get(str(cid)) or {}).get("family") or {}
        for key in ("primary_spouse", "spouse"):
            for x in fam.get(key) or []:
                if isinstance(x, int) and x not in clan_set:
                    sp.add(x)
    print(f"若把族人所记配偶一并画上：+{len(sp)} 人 ⇒ 全族图约 {len(seen) + len(sp)} 珠")
    return 0


if __name__ == "__main__":
    sys.exit(main())
