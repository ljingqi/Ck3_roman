# -*- coding: utf-8 -*-
"""诊断 (只读): 妮卡蕾忒·斯巴达诺斯 (16819577) 的囚禁状态数据面。

用法: tools\\py.ps1 tools\\diag_nikarete.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MELTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "output", "柳特佩特", "data")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "output", "柳特佩特", "data", "player_38653.json")
TARGETS = {"16819577": "妮卡蕾忒", "44470": "卡利斯托斯", "12593": "凯撒里奥斯"}


def char_record(melt, cid):
    """从熔件 dict 取角色对象 (living 优先, 再 dead_unprunable)。"""
    for key in ("living", "dead_unprunable"):
        rec = (melt.get(key) or {}).get(str(cid))
        if isinstance(rec, dict):
            return rec
    return None


def main():
    cache = json.load(open(os.path.abspath(CACHE), encoding="utf-8"))
    import cache_lib as cl

    print("### 缓存侧 (逐档差分结果)")
    for cid, label in TARGETS.items():
        rec = (cache.get("characters") or {}).get(cid) or {}
        print(f"-- {cid} {label}")
        for m in rec.get("memories") or []:
            print("   ", m.get("creation_date"), m.get("type"),
                  json.dumps(m.get("participants"), ensure_ascii=False))
        print("    traits:", rec.get("traits"))

    print()
    print("### 熔件原始侧: alive_data.prison_data (存在 = 该档仍是囚犯)")
    for fn in sorted(os.listdir(os.path.abspath(MELTS))):
        if not fn.startswith("melt_") or "_idx" in fn or not fn.endswith(".json"):
            continue
        melt = cl.load_melt(os.path.join(os.path.abspath(MELTS), fn))
        d = (melt.get("meta_data") or {}).get("date") or melt.get("date") or fn
        out = []
        for cid, label in TARGETS.items():
            rec = char_record(melt, cid)
            if rec is None:
                out.append(f"{label}=不在档")
                continue
            pd = (rec.get("alive_data") or {}).get("prison_data")
            if isinstance(pd, dict):
                out.append(f"{label}=囚({pd.get('type')}@{pd.get('date')},"
                           f"主{pd.get('imprisoner')})")
            else:
                out.append(f"{label}=自由")
        print(f"-- {fn} ({d}): " + " | ".join(out))


if __name__ == "__main__":
    main()
