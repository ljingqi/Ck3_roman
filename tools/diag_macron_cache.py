# -*- coding: utf-8 -*-
"""马克龙十问：从缓存(player_38677.json)取实际入传的数据面。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_macron_cache.py
"""
import json
import os
import sys

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "tools", "out_macron")
CACHE = os.path.join(ROOT, "output", "马克龙", "data", "player_38677.json")
PID = 38677
WIFE = 15682
JOJO = 43961


def dump(name, obj):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as fp:
        if isinstance(obj, str):
            fp.write(obj)
        else:
            json.dump(obj, fp, ensure_ascii=False, indent=1)
    print(f"  写入 {p}")


def main():
    cache = json.load(open(CACHE, encoding="utf-8"))
    chars = cache.get("characters") or {}
    dump("cache_top_keys.json", sorted(cache.keys()))
    print(f"角色数 {len(chars)}", flush=True)

    # 谁是妻子/乔乔
    for cid in (PID, WIFE, JOJO):
        rec = chars.get(str(cid)) or {}
        dump(f"cache_char_{cid}.json", rec)

    # 妻子与玩家的记忆（时间序）
    for cid in (PID, WIFE, JOJO):
        rec = chars.get(str(cid)) or {}
        mems = sorted(rec.get("memories") or [],
                      key=lambda m: str(m.get("creation_date")))
        dump(f"cache_memories_{cid}.json", mems)
        print(f"{cid} 记忆 {len(mems)} 条", flush=True)

    # 特质履历（全角色，找怀孕一类反复得而复失）
    for cid in (PID, WIFE):
        rec = chars.get(str(cid)) or {}
        dump(f"cache_trait_history_{cid}.json", rec.get("trait_history"))

    # 隐事
    dump("cache_secrets_history.json", cache.get("secrets_history"))
    print("隐事已导出", flush=True)

    # 关系/牵制相关缓存键
    dump("cache_relations.json", cache.get("relations"))

    # 领地
    prec = chars.get(str(PID)) or {}
    dump("cache_landed.json", prec.get("landed"))

    # 妻子在缓存中的其他字段
    wrec = chars.get(str(WIFE)) or {}
    dump("cache_wife_misc.json",
         {k: v for k, v in wrec.items() if k not in ("memories", "trait_history")})


if __name__ == "__main__":
    sys.exit(main())
