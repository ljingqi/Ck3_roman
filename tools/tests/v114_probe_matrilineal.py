# -*- coding: utf-8 -*-
"""v114 probe (cache only): the game's own 入赘 (matrilineal) marriage list vs the tree's parent picks."""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import facts as F     # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
cache = json.load(io.open(os.path.join(DATA, "player_207044.json"), encoding="utf-8"))
names = json.load(io.open(os.path.join(DATA, "names.json"), encoding="utf-8"))
chars = cache.get("characters") or {}
tree = json.load(io.open(os.path.join(DATA, "genealogy.json"), encoding="utf-8"))
N = {n["id"]: n for n in tree["nodes"]}
mp = cache.get("matrilineal_pairs") or {}
print("matrilineal_pairs 类型", type(mp).__name__, "条数", len(mp))
items = mp.items() if isinstance(mp, dict) else enumerate(mp)
pairs = []
for kk, vv in items:
    if isinstance(vv, list):
        pairs.append((kk, vv))
    else:
        pairs.append((kk, vv))
print("样例:", json.dumps(list(mp.items())[:6] if isinstance(mp, dict) else mp[:6],
                          ensure_ascii=False))


def nm(cid):
    return (chars.get(str(cid)) or {}).get("name_full") or (chars.get(str(cid)) or {}).get("name_zh") \
        or (names.get(str(cid)) if isinstance(names, dict) else None) or str(cid)


# every parent pair of a tree node, with the game's matrilineal flag
print("\n== 图上每个节点的父母对（父母都在图上）==")
for n in tree["nodes"]:
    x = n["id"]
    fam = (chars.get(str(x)) or {}).get("family") or {}
    fa = [y for y in (fam.get("father") or []) if isinstance(y, int)]
    mo = [y for y in (fam.get("mother") or []) if isinstance(y, int)]
    fa_t = [y for y in fa if y in N]
    mo_t = [y for y in mo if y in N]
    if fa_t and mo_t:
        mat = None
        key_variants = [(fa_t[0], mo_t[0]), (str(fa_t[0]), str(mo_t[0]))]
        for kv in key_variants:
            if isinstance(mp, dict) and kv in mp:
                mat = mp[kv]
        if isinstance(mp, list):
            for row in mp:
                if isinstance(row, dict) and {str(row.get("a")), str(row.get("b"))} == {str(fa_t[0]), str(mo_t[0])}:
                    mat = row
        print(f"  {x} {n['name']}: 父={nm(fa_t[0])} 母={nm(mo_t[0])} → 图上挂={nm(n['parent'])} "
              f"matrilineal_pairs={json.dumps(mat, ensure_ascii=False)}")

print("\n== 图上所有 母系在图上、父不在 的节点（挂母系）==")
for n in tree["nodes"]:
    x = n["id"]
    fam = (chars.get(str(x)) or {}).get("family") or {}
    fa = [y for y in (fam.get("father") or []) if isinstance(y, int)]
    mo = [y for y in (fam.get("mother") or []) if isinstance(y, int)]
    if any(m in N for m in mo) and not any(a in N for a in fa):
        print(f"  {x} {n['name']}: 父={[nm(a) for a in fa]} 母={[nm(m) for m in mo]} → {nm(n['parent'])}")
