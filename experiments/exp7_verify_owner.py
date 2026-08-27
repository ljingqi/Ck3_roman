# -*- coding: utf-8 -*-
"""查证: 真实仇人 10692 / 前妻 13386 / 记忆归属 (经 alive_data.memories)。"""
import json

MELT = r"D:\Journal\expck3\data\melt_869_02_22.json"

def mems_of(c, db):
    ids = (c.get("alive_data") or {}).get("memories") or []
    out = []
    for mid in ids:
        e = db.get(str(mid))
        if e:
            e = dict(e)
            e["_id"] = mid
            out.append(e)
    return out

def main():
    with open(MELT, encoding="utf-8") as fp:
        data = json.load(fp)
    chars = {}
    chars.update(data.get("living") or {})
    chars.update(data.get("dead_unprunable") or {})
    chars.update((data.get("characters") or {}).get("dead_prunable") or {})
    db = data.get("character_memory_manager", {}).get("database") or {}

    for cid in ("10692", "13386", "9363"):
        c = chars.get(cid)
        print(f"\n===== 角色 {cid}: {c.get('first_name') if c else '不存在'} =====")
        if not c:
            continue
        print("  dead_data:", c.get("dead_data"))
        print("  family:", json.dumps(c.get("family_data"), ensure_ascii=False)[:200])
        mems = mems_of(c, db)
        print(f"  alive_data.memories → {len(mems)} 条记忆:")
        for e in mems:
            print(f"    [{e.pop('_id')}] {json.dumps(e, ensure_ascii=False)[:240]}")

    # 记忆 ID 11368 (之前误读为玩家记忆) 的真实归属
    print("\n===== 记忆 ID=11368 归属排查 =====")
    print("  database[11368]:", json.dumps(db.get("11368"), ensure_ascii=False)[:200])
    for cid, c in chars.items():
        ids = (c.get("alive_data") or {}).get("memories") or []
        if 11368 in ids:
            print(f"  属于角色 {cid} ({c.get('first_name')})")

    # 玩家 lost_title 7305 的标题
    print("\n===== 玩家记忆 7305 (lost_title 867.9.8) 完整 =====")
    print(json.dumps(db.get("7305"), ensure_ascii=False, indent=1)[:600])

if __name__ == "__main__":
    main()
