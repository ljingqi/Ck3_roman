# -*- coding: utf-8 -*-
"""实验2: 跨年度存档记忆对比 — 验证「每角色每档一条记忆, 跨年累积补全历史」。

对比 868.1.1 / 869.1.1 / 869.2.22 三个存档中主角及相关人物的记忆:
  若同一角色在不同年份的记忆不同 → 证明存档只保留每角色最新一条,
  跨年自动存档缓存是补全人物记忆历史的正确方案。
"""
import json, os, sys

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FILES = {
    "868.1.1": os.path.join(DATA, "melt_868_01_01.json"),
    "869.1.1": os.path.join(DATA, "melt_869_01_01.json"),
    "869.2.22": os.path.join(DATA, "melt_869_02_22.json"),
}
PID = 11368

def load(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)

def mem_of(db, cid):
    e = db.get(str(cid))
    if e is None:
        return None
    if isinstance(e, list):
        return e
    return [e]

def brief(e):
    return {
        "type": e.get("type"),
        "participants": e.get("participants"),
        "date": e.get("creation_date"),
        "vars": [f.get("flag") for f in (e.get("variables") or {}).get("data") or []],
    }

def main():
    melts = {}
    for label, path in FILES.items():
        if not os.path.isfile(path):
            print(f"[缺] {path}")
            continue
        melts[label] = load(path)
        print(f"已加载 {label}: living={len(melts[label].get('living') or {})} "
              f"记忆库={len(melts[label].get('character_memory_manager', {}).get('database') or {})}")

    # 1) 主角记忆随年份变化
    print("\n=== 主角 11368 记忆随年份变化 ===")
    for label, m in melts.items():
        mems = mem_of(m["character_memory_manager"]["database"], PID)
        print(f"  {label}: {[brief(e) for e in mems] if mems else None}")

    # 2) 家族成员记忆变化
    print("\n=== 边氏家族成员记忆随年份变化 ===")
    fam = ["13136", "13251", "13252", "13530", "39250"]
    for cid in fam:
        print(f"  --- 角色 {cid} ---")
        for label, m in melts.items():
            db = m["character_memory_manager"]["database"]
            mems = mem_of(db, cid)
            print(f"    {label}: {[brief(e) for e in mems] if mems else '无记忆'}")

    # 3) 全库记忆条数随年份
    print("\n=== 记忆库总量随年份 ===")
    for label, m in melts.items():
        db = m["character_memory_manager"]["database"]
        print(f"  {label}: {len(db)}")

    # 4) 找几个跨年记忆确实不同的角色 (证明"最新一条"假设)
    print("\n=== 跨年记忆确实变化的角色样本 ===")
    labels = list(melts.keys())
    if len(labels) >= 2:
        db0 = melts[labels[0]]["character_memory_manager"]["database"]
        db1 = melts[labels[-1]]["character_memory_manager"]["database"]
        changed = []
        for cid in set(db0) & set(db1):
            a = brief(db0[cid]) if isinstance(db0[cid], dict) else None
            b = brief(db1[cid]) if isinstance(db1[cid], dict) else None
            if a and b and a.get("type") != b.get("type"):
                changed.append((cid, a, b))
        print(f"  两档间记忆类型变化的角色数: {len(changed)}")
        for cid, a, b in changed[:10]:
            print(f"    {cid}: {a.get('type')}({a.get('date')}) → {b.get('type')}({b.get('date')})")

    # 5) 死人记忆跨年保持 (同一死人两档都有同一条记忆?)
    print("\n=== 死人记忆跨年一致性 ===")
    if len(labels) >= 2:
        db0 = melts[labels[0]]["character_memory_manager"]["database"]
        db1 = melts[labels[-1]]["character_memory_manager"]["database"]
        du0 = melts[labels[0]].get("dead_unprunable") or {}
        same = 0; total = 0
        for cid, e in db0.items():
            if cid not in du0:
                continue
            if cid in db1 and isinstance(db1[cid], dict) and isinstance(e, dict):
                total += 1
                if db1[cid].get("type") == e.get("type") and db1[cid].get("creation_date") == e.get("creation_date"):
                    same += 1
        print(f"  两档均在且记忆完全一致: {same}/{total}")

if __name__ == "__main__":
    main()

# 废弃声明 (2026-08-27 修正)
# 本脚本基于 v1 的错误假设「character_memory_manager.database 键 = 角色 id」。
# 实测真相: database 键 = 记忆 id (与角色共享 id 池); 角色经 alive_data.memories
# (记忆 id 列表) 持有记忆, 每角色可有多条; 角色死亡时 memories 被清空。
# 正确实验见 exp6/exp7/exp8/exp9, 正确实现在 cache_lib.py (v2)。
