# -*- coding: utf-8 -*-
"""实验3: 记忆键编码深挖 — 高位键是否表示同一角色的多条记忆。

假设: 键 = (记忆块号 << 24) | 角色ID。
验证: 低24位相同的键数量 / 高8位分布 / 玩家 11368 的全部记忆键。
"""
import json, sys
from collections import Counter

MELT = sys.argv[1] if len(sys.argv) > 1 else r"D:\Journal\expck3\data\melt_869_02_22.json"

def main():
    with open(MELT, encoding="utf-8") as fp:
        data = json.load(fp)
    db = data.get("character_memory_manager", {}).get("database") or {}
    living = data.get("living") or {}
    du = data.get("dead_unprunable") or {}

    print("键总数:", len(db))

    # 1) 高8位分布
    hi = Counter()
    for k in db:
        ki = int(k)
        hi[ki >> 24] += 1
    print("\n高8位(键>>24)分布:", dict(sorted(hi.items())))

    # 2) 低24位相同的键 (同一角色的多条记忆)
    by_low = Counter()
    for k in db:
        by_low[int(k) & 0xFFFFFF] += 1
    multi = {cid: n for cid, n in by_low.items() if n > 1}
    print(f"\n低24位出现多次的角色数: {len(multi)}")
    top = sorted(multi.items(), key=lambda x: -x[1])[:12]
    for cid, n in top:
        keys = [k for k in db if int(k) & 0xFFFFFF == cid]
        name = (living.get(str(cid)) or du.get(str(cid)) or {}).get("first_name")
        print(f"  角色 {cid} ({name}) 有 {n} 条记忆: 键={keys}")
        for k in keys:
            e = db[k]
            print(f"      {k}: {e.get('type')} {e.get('creation_date')}")

    # 3) 玩家 11368 的全部记忆键
    print("\n玩家 11368 的全部记忆键:")
    for k in sorted(db, key=int):
        if int(k) & 0xFFFFFF == 11368:
            print(f"  {k}: {json.dumps(db[k], ensure_ascii=False)[:200]}")

    # 4) 直接检查键=16781472 等 (0x1000000|13136)
    for probe in (16781472, 16777216 + 13251, 16777216 + 13530, 16777216 + 39250):
        if str(probe) in db:
            print(f"\nprobe {probe} 存在: {json.dumps(db[str(probe)], ensure_ascii=False)[:250]}")
        else:
            print(f"\nprobe {probe} 不存在")

if __name__ == "__main__":
    main()

# 废弃声明 (2026-08-27 修正)
# 本脚本基于 v1 的错误假设「character_memory_manager.database 键 = 角色 id」。
# 实测真相: database 键 = 记忆 id (与角色共享 id 池); 角色经 alive_data.memories
# (记忆 id 列表) 持有记忆, 每角色可有多条; 角色死亡时 memories 被清空。
# 正确实验见 exp6/exp7/exp8/exp9, 正确实现在 cache_lib.py (v2)。
