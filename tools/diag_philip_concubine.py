# -*- coding: utf-8 -*-
"""菲利普档：妾/囚禁的存档事实核查（问题1 的「先婚后囚」误读）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_philip_concubine.py [名字子串]
"""
import io
import json
import os
import sys

CACHE = r"D:\Roman\output\菲利普\data\player_38691.json"
NEEDLE = sys.argv[1] if len(sys.argv) > 1 else "戈迪娜"


def main():
    c = json.load(io.open(CACHE, encoding="utf-8"))
    ch = c["characters"]
    pid = str(c["player_id"])
    print("player", pid, c.get("player_name"), "last_date", c.get("last_date"),
          "sources", len(c.get("sources") or []))
    p = ch[pid]
    fam = p.get("family") or {}
    print("玩家 family:", json.dumps({k: v for k, v in fam.items()
                                      if k in ("primary_spouse", "spouse",
                                               "concubine", "former_concubines",
                                               "ever_spouses", "child")},
                                     ensure_ascii=False))
    # 找名字含 NEEDLE 的角色
    hits = [cid for cid, r in ch.items()
            if NEEDLE in str(r.get("name_zh") or "")]
    print(f"名字含「{NEEDLE}」的角色:", hits)
    for cid in hits + [str(x) for x in (fam.get("concubine") or [])]:
        r = ch.get(str(cid))
        if not r:
            print(f"--- {cid} 不在缓存")
            continue
        print(f"--- {cid} {r.get('name_zh')} female={r.get('female')} "
              f"birth={r.get('birth')}")
        print("    family:", json.dumps(r.get("family"), ensure_ascii=False))
        print("    court:", json.dumps(r.get("court"), ensure_ascii=False))
        for m in r.get("memories") or []:
            if "prison" in str(m.get("type")):
                print("    MEM", json.dumps(m, ensure_ascii=False))
    # 全员：谁被玩家囚禁
    print("\n被玩家囚禁过的记忆（players 侧 imprisoned_other）：")
    for m in p.get("memories") or []:
        if m.get("type") == "imprisoned_other":
            v = (m.get("participants") or {}).get("imprisoned")
            print(f"    {m.get('creation_date')} → {v} "
                  f"{ch.get(str(v), {}).get('name_zh')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
