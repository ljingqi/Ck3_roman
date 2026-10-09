# -*- coding: utf-8 -*-
"""v117 取证探针 · 第六段：为什么 44503 进不了 player_17066495.json 的 characters 目标集。

cache_lib.merge_cache_save 的目标集规则（cache_lib.py:2739-2752）：玩家本人 + 其 family_data
亲属 + **所有 dynasty_house 与玩家相同的角色**。这里比对玩家与洪天贵福的 house id。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cache_lib as cl  # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
OUT = os.path.join(ROOT, "logs", "v117_probe_gf.txt")
_buf = []


def P(*a):
    s = " ".join(str(x) for x in a)
    _buf.append(s)
    print(s, flush=True)


def info(fn, pid):
    c = cl.load_cache(os.path.join(DATA, fn))
    ch = c.get("characters") or {}
    p = ch.get(str(pid)) or {}
    houses = {}
    for k, r in ch.items():
        h = (r or {}).get("dynasty_house")
        houses[h] = houses.get(h, 0) + 1
    P(f"\n[gf6] {fn} last_date={c.get('last_date')!r} characters 条数={len(ch)}")
    P(f"[gf6]   玩家 {pid}: dynasty_house={p.get('dynasty_house')!r} house_name={p.get('house_name')!r} "
      f"dynasty_name={p.get('dynasty_name')!r} name_zh={p.get('name_zh')!r} culture={p.get('culture')!r}")
    P(f"[gf6]   house 分布 top: {sorted(houses.items(), key=lambda kv: -kv[1])[:8]}")
    for cid in (44503, 38957):
        r = ch.get(str(cid)) or {}
        P(f"[gf6]   characters[{cid}] 存在={bool(r)} dynasty_house={r.get('dynasty_house')!r} "
          f"death={(r.get('death') or {}).get('date')!r} name_zh={r.get('name_zh')!r}")
    del c


def main():
    P("\n" + "=" * 78)
    P("== [gf6] 目标集 house 归属对照 ==")
    for fn, pid in (("player_17066495.json", 17066495),
                    ("player_50565938.json", 50565938),
                    ("player_67408343.json", 67408343)):
        try:
            info(fn, pid)
        except Exception as e:  # noqa: BLE001
            P(f"[gf6] {fn} 失败: {e}")
    with open(OUT, "a", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")


if __name__ == "__main__":
    main()
