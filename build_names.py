# -*- coding: utf-8 -*-
"""构建全量角色名本地化映射表 → data/names.json (v2, 含姓氏; v14 含宗族名)

结构: {"schema": 2, "source": "<档期>", "names": {
        "<角色id>": {"first_name": "...", "name_zh": "...", "house_name": "...",
                     "dynasty_name": "..."}}}
用途: 传记/其它输出查名兜底 (缓存只收录主角相关人物, 此表覆盖全档; house_name
      供姓名合并: 边 + 诚 → 边诚; dynasty_name 为东方名序的姓: 藤原 + 道真)。

用法:
  python build_names.py [melt路径]   # 缺省取日期最新的一份 melt (战役文件夹优先)
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
    """取日期最新的一份熔件: 战役文件夹 output/<家族>/data/ 优先, 兼容旧根目录。
    v28: 本表按角色 id 索引, **只在同一战役内有效** — 默认选最新日期仅为兜底,
    推荐显式传本战役熔件: `python build_names.py output/<家族>/data/melt_<日期>.json`。"""
    pat = re.compile(r"melt_(\d+_\d{2}_\d{2})(?:_p\d+)?\.json$")
    best, best_path = None, None
    dirs = []
    out = os.path.join(HERE, "output")
    if os.path.isdir(out):
        for folder in os.listdir(out):
            d = os.path.join(out, folder, "data")
            if os.path.isdir(d):
                dirs.append(d)
    if os.path.isdir(DATA):
        dirs.append(DATA)
    for d in dirs:
        for fn in os.listdir(d):
            m = pat.match(fn)
            if not m:
                continue
            date = ".".join(str(int(x)) for x in m.group(1).split("_"))
            if best is None or cl.date_key(date) > cl.date_key(best):
                best, best_path = date, os.path.join(d, fn)
    return best_path


def _campaign_folder(melt_path):
    """melt 所在战役文件夹名 (output/<家族>/data/x.json → <家族>); 非该布局返回 ''。"""
    d = os.path.dirname(os.path.abspath(melt_path))
    if os.path.basename(d) != "data":
        return ""
    folder = os.path.dirname(d)
    if os.path.dirname(folder) != os.path.abspath(os.path.join(HERE, "output")):
        return ""
    return os.path.basename(folder)


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
        # v14: 宗族名 (东方名序的姓): 家族 → 宗族 → 解析
        dn = ""
        hid = c.get("dynasty_house")
        if hid is not None:
            did = cl.dynasty_id_of(melt, hid)
            if did is not None:
                dn = cl.dynasty_name_zh(melt, did) or ""
        names[cid] = {
            "first_name": fn,
            "name_zh": nm,
            "house_name": h,
            "dynasty_name": dn,
        }
    out = {
        "schema": 2,
        "source": melt.get("date"),
        # v28: 战役号 — 角色 id 只在同一战役内有意义, 跨战役表会被 display_name 弃用
        "playthrough_id": melt.get("playthrough_id"),
        "total": len(names),
        "names": names,
    }
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False)
    # v28: 同时写一份**战役内**副本 — 传记优先读 output/<家族>/data/names.json,
    # 全局 data/names.json 只作跨战役兜底 (角色 id 跨战役复用)。
    folder = _campaign_folder(melt_path)
    if folder:
        local = os.path.join(HERE, "output", folder, "data", "names.json")
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "w", encoding="utf-8") as fp:
            json.dump(out, fp, ensure_ascii=False)
        print(f"已生成战役内人名表 {local} (战役 {out['playthrough_id']})")
    elif not out["playthrough_id"]:
        print("提示: 本熔件无战役号, 全局表可能跨战役错配 — 建议传本战役熔件路径")
    print(f"已生成 {OUT}: {len(names)} 个角色 (来源 {out['source']})")
    for cid in ("11368", "10692", "13386", "39250", "10818", "10798", "9455", "11990"):
        n = names.get(cid)
        if n:
            print(f"  {cid}: 家族{n.get('house_name')} 宗族{n.get('dynasty_name')} "
                  f"名{n.get('name_zh')} → {n.get('dynasty_name')}{n.get('name_zh')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
