# -*- coding: utf-8 -*-
"""v114 probe (cache only): which tree parent-pairs the game records as 入赘 (matrilineal)."""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
cache = json.load(io.open(os.path.join(DATA, "player_207044.json"), encoding="utf-8"))
tree = json.load(io.open(os.path.join(DATA, "genealogy.json"), encoding="utf-8"))
N = {n["id"]: n for n in tree["nodes"]}
chars = cache.get("characters") or {}
mp = cache.get("matrilineal_pairs") or {}
print("matrilineal_pairs:", len(mp), "条；键形如", list(mp.items())[:2])


def nm(cid):
    c = chars.get(str(cid)) or {}
    return c.get("name_full") or c.get("name_zh") or (N.get(cid) or {}).get("name") or str(cid)


print("\n== 图上节点：父母都在图上者，游戏记的入赘与否 ==")
n_mat = 0
for n in tree["nodes"]:
    x = n["id"]
    fam = (chars.get(str(x)) or {}).get("family") or {}
    fa = [y for y in (fam.get("father") or []) if isinstance(y, int) and y in N]
    mo = [y for y in (fam.get("mother") or []) if isinstance(y, int) and y in N]
    if fa and mo:
        key = f"{min(fa[0], mo[0])}>{max(fa[0], mo[0])}"
        mat = mp.get(key)
        if mat:
            n_mat += 1
        print(f"  {x:10d} {n['name']:22s} {nm(fa[0])} > {nm(mo[0]):18s} "
              f"入赘={mat!r} 图上挂={nm(n['parent'])}")
print(f"-- 其中游戏记为入赘者 {n_mat} 例")

print("\n== 图上所有 入赘婚（游戏记载）当事人对 ==")
for key, date in mp.items():
    try:
        a, b = (int(v) for v in key.split(">"))
    except Exception:
        continue
    if a in N or b in N:
        print(f"  {key} ({nm(a)} > {nm(b)}) since {date}  "
              f"图上={a in N}/{b in N} 挂={'—' if a not in N else nm(N[a]['parent'])}")
