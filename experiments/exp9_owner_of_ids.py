# -*- coding: utf-8 -*-
"""查证: 记忆ID 13136/13251/13252/13530 的真实 owner (v2 归属修正)。"""
import json

MELT = r"D:\Journal\expck3\data\melt_869_02_22.json"

def main():
    m = json.load(open(MELT, encoding="utf-8"))
    chars = {}
    chars.update(m.get("living") or {})
    chars.update(m.get("dead_unprunable") or {})
    chars.update((m.get("characters") or {}).get("dead_prunable") or {})
    db = m.get("character_memory_manager", {}).get("database") or {}

    for mid in ("13136", "13251", "13252", "13530", "16781472", "16777220"):
        e = db.get(mid)
        owners = [cid for cid, c in chars.items()
                  if int(mid) in (c.get("alive_data") or {}).get("memories", [])]
        etext = json.dumps(e, ensure_ascii=False)[:180] if e else "无"
        print(f"记忆ID {mid}: {etext}")
        print(f"   owner: {owners[:6]}")

if __name__ == "__main__":
    main()
