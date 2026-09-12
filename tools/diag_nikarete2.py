# -*- coding: utf-8 -*-
"""诊断 (只读): 妮卡蕾忒 (16819577) 的囚禁记录全链路 —— 含秃头查理侧。

用法: tools\\py.ps1 tools\\diag_nikarete2.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

DATA = os.path.join(ROOT, "output", "柳特佩特", "data")
TARGET = 16819577
CHARLES = 12154
PID = 38653


def hit(mem, ids):
    parts = mem.get("participants") or {}
    return any(isinstance(v, int) and v in ids for v in parts.values())


def main():
    for fn in sorted(os.listdir(DATA)):
        if not fn.startswith("melt_") or "_idx" in fn:
            continue
        melt = cl.load_melt(os.path.join(DATA, fn))
        mm = (melt.get("character_memory_manager") or {}).get("database") or {}
        d = (melt.get("meta_data") or {}).get("date") or melt.get("date") or fn
        print("=" * 72)
        print(f"## {fn}  ({d})")
        n = 0
        for mid, m in mm.items():
            if not isinstance(m, dict):
                continue
            if hit(m, {TARGET, CHARLES}):
                print("   mem", mid, m.get("creation_date"), m.get("type"),
                      json.dumps(m.get("participants"), ensure_ascii=False))
                n += 1
        if n == 0:
            print("   (无涉及妮卡蕾忒或秃头查理的记忆)")
        # 角色记录本身
        for key in ("living", "dead_unprunable"):
            for cid, label in ((TARGET, "妮卡蕾忒"), (CHARLES, "秃头查理")):
                rec = (melt.get(key) or {}).get(str(cid))
                if not isinstance(rec, dict):
                    continue
                ad = rec.get("alive_data") or {}
                print(f"   [{key}] {label}: prison_data="
                      + json.dumps(ad.get("prison_data"), ensure_ascii=False)
                      + " | court_data=" + json.dumps(rec.get("court_data"),
                                                     ensure_ascii=False)[:160])
                # variables 里的相关 flag
                for v in (ad.get("variables") or {}).get("data") or []:
                    fl = str(v.get("flag") or "")
                    if any(k in fl for k in ("ransom", "prison", "arrest", "hostage",
                                             "captive")):
                        print("        flag:", json.dumps(v, ensure_ascii=False))
        # 玩家侧 prisoners 列表类字段
        pl = (melt.get("living") or {}).get(str(PID)) or {}
        for k in ("prisoners", "prisoner", "hostages"):
            if k in pl:
                print("   玩家字段", k, json.dumps(pl[k], ensure_ascii=False)[:200])


if __name__ == "__main__":
    main()
