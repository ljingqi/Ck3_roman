# -*- coding: utf-8 -*-
"""实验1: 非玩家家族 NPC 角色死后记忆保留性检测。

数据源: expck3/data/melt_869_02_22.json (rakaly json 熔化结果)。
检测点:
  A. dead_unprunable / dead_prunable / living 中在记忆库有键的数量
  B. 抽检 NPC 死人(非玩家家族)的记忆内容
  C. 记忆类型 x 死活 分布
  D. 记忆清理迹象: 记忆 end_date 早于存档日期的比例 / prune 队列
"""
import json, os, sys
from collections import Counter

MELT = sys.argv[1] if len(sys.argv) > 1 else r"D:\Journal\_scratch\ck3_melt.json"

def main():
    with open(MELT, encoding="utf-8") as fp:
        data = json.load(fp)
    living = data.get("living") or {}
    du = data.get("dead_unprunable") or {}
    dp = (data.get("characters") or {}).get("dead_prunable") or {}
    db = data.get("character_memory_manager", {}).get("database") or {}
    date = data.get("date")

    print(f"存档日期: {date}")
    print(f"living={len(living)} dead_unprunable={len(du)} dead_prunable={len(dp)} 记忆库={len(db)}")

    def in_mem(cid):
        return str(cid) in db

    # A. 记忆键归属
    mem_living = sum(1 for cid in living if in_mem(cid))
    mem_du = sum(1 for cid in du if in_mem(cid))
    mem_dp = sum(1 for cid in dp if in_mem(cid))
    print(f"\n[A] 有记忆的角色: living={mem_living}/{len(living)} "
          f"dead_unprunable={mem_du}/{len(du)} dead_prunable={mem_dp}/{len(dp)}")

    # B. NPC 死人记忆样本 (非玩家家族: 从 dead 中抽几个有记忆的)
    print("\n[B] dead_unprunable 中有记忆的 NPC 样本(前8):")
    shown = 0
    for cid, c in du.items():
        if in_mem(cid):
            print(f"  dead {cid} {c.get('first_name')}: {json.dumps(db[cid], ensure_ascii=False)[:260]}")
            shown += 1
            if shown >= 8:
                break

    # B2. dead_prunable 中有记忆的
    print("\n[B2] dead_prunable 中有记忆的样本(前5):")
    shown = 0
    for cid, c in dp.items():
        if in_mem(cid):
            print(f"  dead_prunable {cid} {c.get('first_name')}: {json.dumps(db[cid], ensure_ascii=False)[:260]}")
            shown += 1
            if shown >= 5:
                break

    # C. 记忆类型分布按死活
    print("\n[C] 记忆类型 x 死活 分布 (前15):")
    cnt_alive = Counter()
    cnt_dead = Counter()
    for cid, e in db.items():
        t = e.get("type") if isinstance(e, dict) else "?"
        if cid in living:
            cnt_alive[t] += 1
        elif cid in du or cid in dp:
            cnt_dead[t] += 1
    print("  类型 | 活人 | 死人")
    for t in sorted(set(list(cnt_alive) + list(cnt_dead)),
                    key=lambda x: -(cnt_alive[x] + cnt_dead[x]))[:15]:
        print(f"  {t:28} {cnt_alive[t]:>5} {cnt_dead[t]:>5}")

    # D. 记忆过期检查
    print("\n[D] 记忆过期/清理迹象:")
    expired = 0
    noend = 0
    total = 0
    for e in db.values():
        if not isinstance(e, dict):
            continue
        total += 1
        ed = e.get("end_date")
        if not ed:
            noend += 1
            continue
        # 比较年月日
        try:
            ey = int(ed.split(".")[0]); dy = int(date.split(".")[0])
            if ey < dy:
                expired += 1
        except Exception:
            pass
    print(f"  记忆总数={total} 无end_date={noend} end_date年份<存档年份(疑似已过期仍保留)={expired}")
    print("  prune_queue:", json.dumps((data.get('characters') or {}).get('prune_queue'), ensure_ascii=False)[:100])

    # E. 玩家家族与 NPC 对比: 玩家家族成员(同 dynasty_house)的记忆
    print("\n[E] 玩家家族(边氏 dynn_Bian_908A)成员记忆:")
    pc = living.get("11368") or {}
    house = pc.get("dynasty_house")
    fam = [cid for cid, c in living.items() if c.get("dynasty_house") == house]
    print(f"  活着的同族 {len(fam)} 人, 有记忆 {sum(1 for c in fam if in_mem(c))} 人")
    for cid in fam[:12]:
        e = db.get(cid)
        if e:
            print(f"    {cid} {living[cid].get('first_name')}: {json.dumps(e, ensure_ascii=False)[:200]}")

if __name__ == "__main__":
    main()

# 废弃声明 (2026-08-27 修正)
# 本脚本基于 v1 的错误假设「character_memory_manager.database 键 = 角色 id」。
# 实测真相: database 键 = 记忆 id (与角色共享 id 池); 角色经 alive_data.memories
# (记忆 id 列表) 持有记忆, 每角色可有多条; 角色死亡时 memories 被清空。
# 正确实验见 exp6/exp7/exp8/exp9, 正确实现在 cache_lib.py (v2)。
