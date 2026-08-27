# -*- coding: utf-8 -*-
"""构建全量角色名本地化映射表 → data/names.json (v2, 含姓氏)

结构: {"schema": 2, "source": "<档期>", "names": {
        "<角色id>": {"first_name": "...", "name_zh": "...", "house_name": "..."}}}
用途: 传记/其它输出查名兜底 (缓存只收录主角相关人物, 此表覆盖全档; house_name
      供姓名合并: 边 + 诚 → 边诚)。

用法:
  python build_names.py [melt路径]   # 缺省取 data/ 下日期最新的一份 melt
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cache_lib as cl

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "data", "names.json")


def _latest_melt():
    melts = [f for f in os.listdir(DATA)
             if re.match(r"melt_\d+_\d{2}_\d{2}\.json$", f)]
    if not melts:
        return None
    melts.sort(key=lambda f: cl.date_key(f[5:-5].replace("_", ".")))
    return os.path.join(DATA, melts[-1])


def main():
    melt_path = sys.argv[1] if len(sys.argv) > 1 else _latest_melt()
    if not melt_path or not os.path.isfile(melt_path):
        print(f"找不到 melt 文件: {melt_path} (先运行 pipeline.py scan 或指定路径)")
        return 1
    melt = cl.load_melt(melt_path)
    chars = cl.all_characters(melt)
    names = {}
    for cid, c in chars.items():
        fn = c.get("first_name")
        if not fn:
            continue
        nm = cl.name_zh(c)
        if not nm:
            continue
        h = cl.house_name_zh(melt, c.get("dynasty_house"))
        names[cid] = {
            "first_name": fn,
            "name_zh": nm,
            "house_name": h,
        }
    out = {
        "schema": 2,
        "source": melt.get("date"),
        "total": len(names),
        "names": names,
    }
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False)
    print(f"已生成 {OUT}: {len(names)} 个角色 (来源 {out['source']})")
    for cid in ("11368", "10692", "13386", "39250", "10818", "10798", "9455", "11990"):
        n = names.get(cid)
        if n:
            print(f"  {cid}: {n.get('house_name')}{n.get('name_zh')} "
                  f"(house={n.get('house_name')}, name={n.get('name_zh')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
