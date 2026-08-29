# -*- coding: utf-8 -*-
"""修复缓存 house_name: 用新取值链 (本地化表优先) 重解析, 重建 name_full。
只读逻辑; 会写回缓存 JSON。"""
import json
import sys

sys.path.insert(0, r"D:\Roman")
import cache_lib as cl

CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
MELT = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"

def main():
    cache = json.load(open(CACHE, encoding="utf-8"))
    melt = json.load(open(MELT, encoding="utf-8"))
    changed = 0
    samples = []
    for cid, rec in (cache.get("characters") or {}).items():
        hid = rec.get("dynasty_house")
        if hid is None:
            continue
        new = cl.house_name_zh(melt, hid)
        old = rec.get("house_name") or ""
        if new and new != old:
            if len(samples) < 10:
                samples.append((cid, rec.get("name_zh"), old, new))
            rec["house_name"] = new
            nz = rec.get("name_zh") or ""
            rec["name_full"] = (new + nz) if nz else ""
            changed += 1
    print("变更角色数:", changed)
    for s in samples:
        print("  ", s)
    if changed:
        with open(CACHE, "w", encoding="utf-8") as fp:
            json.dump(cache, fp, ensure_ascii=False)
        print("已写回:", CACHE)

if __name__ == "__main__":
    main()
