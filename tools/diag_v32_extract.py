# -*- coding: utf-8 -*-
"""v32 单档快检：一次熔载验证 cache 新字段 (trait_xp 样本 / opinions 纳妾) 与
特质档位名、监禁配对的事实层改动（避免为验证先跑 20 分钟全量重建）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_v32_extract.py [家族] [玩家id] [as_of]
"""
import io
import json
import os
import sys

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)
import cache_lib as cl     # noqa: E402
import facts as F          # noqa: E402
import localization as L   # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "马克龙"
PID = int(sys.argv[2]) if len(sys.argv) > 2 else 38677
AS_OF = sys.argv[3] if len(sys.argv) > 3 else None


def main():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    melts = sorted(x for x in os.listdir(data)
                   if x.startswith("melt_") and "_idx" not in x and x.endswith(".json"))
    paths = [(os.path.join(data, m), ".".join(
        str(int(y)) for y in m[len("melt_"):-len(".json")].split("_")))
        for m in melts]
    paths.sort(key=lambda x: cl.date_key(x[1]))
    if "all" not in sys.argv:
        paths = paths[-1:]          # 默认只载末档 (快检; 全量重建走 rebuild_folder)
    print(f"{FOLDER}: 载入 {len(paths)} 份熔件", flush=True)

    cache = cl.new_cache()
    for path, date in paths:
        melt = cl.load_melt(path)
        cl.extract_snapshot(cache, melt, date)
        print(f"  {date}: 角色 {len(cache['characters'])}, "
              f"opinions {len(cache.get('opinions') or {})}, "
              f"hooks {len(cache.get('hooks') or {})}", flush=True)
        if date == paths[-1][1]:
            last = melt
        del melt

    print("\n=== cache['opinions'] ===")
    for k, v in list((cache.get("opinions") or {}).items())[:12]:
        print("  ", k, json.dumps(v, ensure_ascii=False))

    rec = (cache.get("characters") or {}).get(str(PID)) or {}
    print(f"\n=== 主角 {PID} trait_xp 样本 ({len(rec.get('trait_xp') or [])} 条) ===")
    for s in (rec.get("trait_xp") or [])[:4]:
        print("  ", s.get("from"), "traits", s.get("traits"), "xp", s.get("xp"))

    # 一次全量 facts (含 prison 配对/特质档名), 不调 LLM
    f = F.Facts(cache, last, None, as_of=AS_OF)
    print("\n=== 主角特质 (档位名 + 子轨道) ===")
    print("  ", f.traits_sentence(PID))
    print("   履历:", f.trait_history_lines(PID))
    print("\n=== 强纳为妾句 ===")
    print("  ", f.forced_concubine_lines())
    print("\n=== 时间线里的囚禁/越狱/夭折 ===")
    for e in (F._timeline(f) or []):
        t = e.get("text") or ""
        if any(k in t for k in ("囚", "越狱", "死婴", "孕期")):
            print("  ", e.get("date"), t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
