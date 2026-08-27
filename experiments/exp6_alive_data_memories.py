# -*- coding: utf-8 -*-
"""验证: 角色 alive_data.memories = 记忆ID列表 → database[记忆ID] 取记忆。
玩家 11368 应有**多条**记忆 (杀妻/再娶等事件)。"""
import json

MELT = r"D:\Journal\expck3\data\melt_869_02_22.json"

def main():
    with open(MELT, encoding="utf-8") as fp:
        data = json.load(fp)
    living = data.get("living") or {}
    db = data.get("character_memory_manager", {}).get("database") or {}
    print("database 键数:", len(db))

    pc = living.get("11368") or {}
    ad = pc.get("alive_data") or {}
    print("玩家 alive_data 键:", list(ad.keys()))
    mem_ids = ad.get("memories")
    print("玩家 memories 字段:", mem_ids, "类型:", type(mem_ids).__name__)
    print("\n=== 玩家的所有记忆 (经 alive_data.memories → database) ===")
    if isinstance(mem_ids, list):
        for mid in mem_ids:
            e = db.get(str(mid))
            if e is None:
                print(f"  id={mid}: (database 中无此键)")
                continue
            print(f"  id={mid}: {json.dumps(e, ensure_ascii=False)[:260]}")
    # 验证: 一个拥有多条记忆的角色
    print("\n=== 找一个有多条记忆的角色 ===")
    found = 0
    for cid, c in living.items():
        m = (c.get("alive_data") or {}).get("memories")
        if isinstance(m, list) and len(m) >= 3:
            print(f"角色 {cid} {c.get('first_name')} 记忆ID: {m}")
            for mid in m[:6]:
                e = db.get(str(mid))
                print(f"    id={mid}: {json.dumps(e, ensure_ascii=False)[:200] if e else '无'}")
            found += 1
            if found >= 3:
                break
    # 统计: 角色记忆数量分布 (从 living 抽样)
    print("\n=== living 角色记忆数分布 (抽样1000) ===")
    from collections import Counter
    cnt = Counter()
    n = 0
    for cid, c in living.items():
        m = (c.get("alive_data") or {}).get("memories")
        if isinstance(m, list):
            cnt[len(m)] += 1
        else:
            cnt[0] += 1
        n += 1
        if n >= 1000:
            break
    print("  记忆条数分布:", dict(sorted(cnt.items())))

if __name__ == "__main__":
    main()
