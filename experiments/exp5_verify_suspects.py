# -*- coding: utf-8 -*-
"""实验5: 疑点查证 — 9363/13386/11763/43099/39250 在三个档中的状态。
目的: 厘清「死者记忆」语义 (死期 vs 记忆创建期), 并还原主角婚姻史。
"""
import json, os, sys

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FILES = {
    "868.1.1": os.path.join(DATA, "melt_868_01_01.json"),
    "869.1.1": os.path.join(DATA, "melt_869_01_01.json"),
    "869.2.22": os.path.join(DATA, "melt_869_02_22.json"),
}
PIDS = ["9363", "13386", "11763", "43099", "39250", "11368"]

def main():
    melts = {}
    for label, path in FILES.items():
        with open(path, encoding="utf-8") as fp:
            melts[label] = json.load(fp)

    for cid in PIDS:
        print(f"\n{'='*60}\n角色 {cid}")
        for label, m in melts.items():
            living = m.get("living") or {}
            du = m.get("dead_unprunable") or {}
            dp = (m.get("characters") or {}).get("dead_prunable") or {}
            db = (m.get("character_memory_manager") or {}).get("database") or {}
            if cid in living:
                c = living[cid]
                loc = "living"
            elif cid in du:
                c = du[cid]
                loc = "dead_unprunable"
            elif cid in dp:
                c = dp[cid]
                loc = "dead_prunable"
            else:
                print(f"  {label}: 不存在")
                continue
            fam = (c.get("family_data") or {})
            dd = c.get("dead_data")
            mem = db.get(cid)
            mems = mem if isinstance(mem, list) else ([mem] if mem else [])
            print(f"  {label}[{loc}]: 名={c.get('first_name')} 生={c.get('birth')} "
                  f"dead_data={json.dumps(dd, ensure_ascii=False)}")
            print(f"     family={json.dumps(fam, ensure_ascii=False)[:220]}")
            for e in mems:
                print(f"     记忆: {json.dumps(e, ensure_ascii=False)[:220]}")

if __name__ == "__main__":
    main()

# 废弃声明 (2026-08-27 修正)
# 本脚本基于 v1 的错误假设「character_memory_manager.database 键 = 角色 id」。
# 实测真相: database 键 = 记忆 id (与角色共享 id 池); 角色经 alive_data.memories
# (记忆 id 列表) 持有记忆, 每角色可有多条; 角色死亡时 memories 被清空。
# 正确实验见 exp6/exp7/exp8/exp9, 正确实现在 cache_lib.py (v2)。
