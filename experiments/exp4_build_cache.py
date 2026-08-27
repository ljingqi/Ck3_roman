# -*- coding: utf-8 -*-
"""实验4: 用年度自动存档构建主角相关人物记忆缓存库。

流程: 加载 868.1.1 → 869.1.1 → 869.2.22 三个熔化 JSON,
逐档 extract_snapshot 并入 expck3/cache/memories.json, 然后打印统计。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cache_lib as cl

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "memories.json")

SOURCES = [
    ("868.1.1", os.path.join(DATA, "melt_868_01_01.json")),
    ("869.1.1", os.path.join(DATA, "melt_869_01_01.json")),
    ("869.2.22", os.path.join(DATA, "melt_869_02_22.json")),
]

def main():
    cache = cl.load_cache(CACHE_PATH)
    for label, path in SOURCES:
        if not os.path.isfile(path):
            print(f"[缺] {path}")
            continue
        melt = cl.load_melt(path)
        cl.extract_snapshot(cache, melt, label)
        n_mem = sum(len(c.get("memories") or []) for c in cache["characters"].values())
        print(f"并入 {label}: 相关人物={len(cache['characters'])} 累计记忆={n_mem} 存档来源={cache['sources']}")
    cl.save_cache(cache, CACHE_PATH)
    print("\n缓存已写入:", CACHE_PATH)

    # ---- 统计 ----
    pid = cache["player_id"]
    pc = cache["characters"].get(str(pid)) or {}
    print("\n=== 主角 ===")
    print(f"  id={pid} 名={pc.get('first_name')} 中文={pc.get('name_zh')} 生={pc.get('birth')} 死={pc.get('death')}")
    print(f"  家族: {pc.get('family')}")
    print(f"  记忆({len(pc.get('memories') or [])}):")
    for m in pc.get("memories") or []:
        print(f"    {m['type']} {m.get('creation_date')} first_seen={m.get('first_seen')} parts={m.get('participants')}")

    print("\n=== 主角结仇清单 ===")
    rivals = cl.summarize_relations(cache)
    for r in rivals:
        side = " (对方视角)" if r.get("from_other_side") else ""
        print(f"  {r['other']} {r['other_name']}: {r['type']} @ {r['date']}{side}")

    print("\n=== 相关人物一览 (有记忆者) ===")
    for cid, c in sorted(cache["characters"].items(), key=lambda x: int(x[0])):
        mems = c.get("memories") or []
        death = c.get("death")
        dstr = f" 死:{death.get('date')}/{death.get('reason')}" if death else ""
        print(f"  {cid} {c.get('name_zh')}({c.get('first_name')}) 生:{c.get('birth')}{dstr} 记忆:{len(mems)}")
        for m in mems:
            print(f"      {m['type']} {m.get('creation_date')} first_seen={m.get('first_seen')}")

    print("\n=== 玩家死亡检测 ===")
    print("  cache.player_death =", cache.get("player_death"))

if __name__ == "__main__":
    main()
