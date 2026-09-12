# -*- coding: utf-8 -*-
"""诊断 (只读): 秃头查理 (12154) 的完整记忆列表 + 乱伦线索。

用法: tools\\py.ps1 experiments\\diag_charles_mem.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

DATA = os.path.join(ROOT, "output", "柳特佩特", "data")
CHARLES = "12154"
MELT = "melt_878_01_01.json"


def main():
    melt = cl.load_melt(os.path.join(DATA, MELT))
    chars = melt.get("living") or {}
    db = (melt.get("character_memory_manager") or {}).get("database") or {}
    c = chars.get(CHARLES) or (melt.get("dead_unprunable") or {}).get(CHARLES) or {}
    print("### 秃头查理 12154:", c.get("first_name"),
          "| house", c.get("dynasty_house"), "| birth", c.get("birth"))
    print("   alive_data keys:", list((c.get("alive_data") or {}).keys()))
    ids = (c.get("alive_data") or {}).get("memories") or []
    print("### alive_data.memories:", len(ids), "条")
    for mid in ids:
        m = db.get(str(mid))
        if not isinstance(m, dict):
            print(f"   [{mid}] <不在 database>")
            continue
        print(f"   [{mid}] {m.get('creation_date')} {m.get('type')} "
              + json.dumps(m.get("participants"), ensure_ascii=False))
    print()
    print("### 参与方含 秃头查理 的全部记忆 (database 侧)")
    for mid, m in db.items():
        if not isinstance(m, dict):
            continue
        parts = m.get("participants") or {}
        if int(CHARLES) in [v for v in parts.values() if isinstance(v, int)]:
            print(f"   [{mid}] {m.get('creation_date')} {m.get('type')} "
                  + json.dumps(parts, ensure_ascii=False))
    print()
    print("### 家族关系")
    fam = c.get("family_data") or []
    print("   family_data:", json.dumps(fam, ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
