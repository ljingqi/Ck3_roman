# -*- coding: utf-8 -*-
"""Build the full character-name localization table -> data/names.json: a name-lookup
fallback for the biography output, since the cache only covers characters related to the
player. Each character id maps to {"first_name", "name_zh", "house_name", "dynasty_name"},
where house_name merges given names and dynasty_name is the surname in Eastern name order.
Usage: python build_names.py [melt path] — the newest melt is used by default."""
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
    """Return the newest melt file by date, campaign folders output/<family>/data/ first.

    The table is indexed by character id and is valid only inside one campaign, so passing
    this campaign's melt path explicitly is better: python build_names.py <melt path>."""
    pat = re.compile(r"melt_(\d+_\d{2}_\d{2})(?:_p\d+)?\.json(?:\.gz|\.xz)?$")
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
    """Campaign folder of a melt path (output/<family>/data/x.json -> <family>); '' when the
    path does not fit that layout."""
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
        # playthrough id: character ids are per-campaign only
        "playthrough_id": melt.get("playthrough_id"),
        "total": len(names),
        "names": names,
    }
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False)
    # Per-campaign copy: biographies read output/<family>/data/names.json first, and the
    # global table is only a cross-campaign fallback.
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
