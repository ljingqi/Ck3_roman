# -*- coding: utf-8 -*-
"""关键查证: 死人记忆是否保留 — 对比 13386(阿足) 死前(868.1.1档) 与死后(869档)
的 alive_data.memories; 并统计 dead 角色中 alive_data.memories 非空的比例。"""
import json, os
from collections import Counter

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FILES = {
    "868.1.1": os.path.join(DATA, "melt_868_01_01.json"),
    "869.1.1": os.path.join(DATA, "melt_869_01_01.json"),
    "869.2.22": os.path.join(DATA, "melt_869_02_22.json"),
}

def load(p):
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)

def mem_ids(c):
    return (c.get("alive_data") or {}).get("memories") or []

def main():
    melts = {k: load(v) for k, v in FILES.items()}

    # 1) 阿足跨档
    print("=== 阿足(13386) 跨档 alive_data.memories ===")
    for label, m in melts.items():
        living = m.get("living") or {}
        du = m.get("dead_unprunable") or {}
        dp = (m.get("characters") or {}).get("dead_prunable") or {}
        c = living.get("13386") or du.get("13386") or dp.get("13386")
        if c is None:
            print(f"  {label}: 不存在")
            continue
        loc = "living" if "13386" in living else ("dead_unprunable" if "13386" in du else "dead_prunable")
        print(f"  {label}[{loc}]: memories={mem_ids(c)}")

    # 2) dead 角色中有记忆的比例
    print("\n=== dead 角色 alive_data.memories 统计 (869.2.22) ===")
    m = melts["869.2.22"]
    living = m.get("living") or {}
    du = m.get("dead_unprunable") or {}
    dp = (m.get("characters") or {}).get("dead_prunable") or {}
    for label, pool in (("dead_unprunable", du), ("dead_prunable", dp)):
        with_mem = sum(1 for c in pool.values() if mem_ids(c))
        print(f"  {label}: 有记忆 {with_mem}/{len(pool)}")
    # 抽样展示 dead 有记忆的样本
    print("\n  dead 中有记忆的样本(前6):")
    shown = 0
    for cid, c in du.items():
        ids = mem_ids(c)
        if ids:
            print(f"    {cid} {c.get('first_name')}: {ids[:8]}")
            shown += 1
            if shown >= 6:
                break

    # 3) 记忆 ID 池 vs 角色引用 (键类型统一为 str)
    print("\n=== 记忆 ID 池 vs 角色引用 (869.2.22) ===")
    db = m.get("character_memory_manager", {}).get("database") or {}
    refs = Counter()
    for c in list(living.values()) + list(du.values()) + list(dp.values()):
        for i in mem_ids(c):
            refs[str(i)] += 1
    print(f"  database 记忆总数: {len(db)}")
    print(f"  角色引用到的记忆 ID 数: {len(refs)}")
    unreferenced = [i for i in db if i not in refs]
    print(f"  database 中未被任何角色引用的记忆: {len(unreferenced)}")

    # 4) 关键: 868.1.1 档 living 有记忆的角色, 869.2.22 档若已死, memories 是否还在
    print("\n=== 死前有记忆 → 死后是否保留 ===")
    m0 = melts["868.1.1"]
    living0 = m0.get("living") or {}
    kept = 0
    cleared = 0
    examples = []
    for cid, c in living0.items():
        ids0 = mem_ids(c)
        if not ids0:
            continue
        c2 = du.get(cid) or dp.get(cid)
        if c2 is not None:  # 868 活 → 869 死
            ids2 = mem_ids(c2)
            if ids2:
                kept += 1
            else:
                cleared += 1
                if len(examples) < 5:
                    examples.append((cid, c.get("first_name"), ids0))
    print(f"  868活有记忆→869已死: 记忆保留 {kept} 人, 被清空 {cleared} 人")
    for cid, name, ids0 in examples:
        print(f"    例: {cid} {name} 死前记忆 {ids0} → 死后 memories=[]")
    # 对照: 868活有记忆→869仍活: 记忆还在?
    alive_kept = 0
    alive_total = 0
    for cid, c in living0.items():
        ids0 = mem_ids(c)
        if not ids0:
            continue
        c2 = living.get(cid)
        if c2 is not None:
            alive_total += 1
            if mem_ids(c2):
                alive_kept += 1
    print(f"  对照: 868活有记忆→869仍活: 记忆保留 {alive_kept}/{alive_total}")

if __name__ == "__main__":
    main()
