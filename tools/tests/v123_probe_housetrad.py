# -*- coding: utf-8 -*-
"""v123: why does a house get the western branch wording? Reads a cache only (no melt).

Usage:  python tools/tests/v123_probe_housetrad.py <家族> [<房名片段> ...]
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import cache_lib as cl          # noqa: E402
import llm                      # noqa: E402

FOLDER = sys.argv[1]
WANT = sys.argv[2:] or ["邕州洪", "布雷恩", "哈德良波利斯洪", "闽洪"]


def main():
    cfg = llm.load_config()
    data = os.path.join(cfg.get("output_dir", ""), FOLDER, "data")
    idx = json.load(io.open(os.path.join(data, "_caches_index.json"), encoding="utf-8"))
    files = idx.get("files") or {}
    name = max(files, key=lambda k: cl.date_key((files[k].get("meta") or {}).get("last_date")
                                                or ""))
    path = os.path.join(data, name)
    print("cache:", os.path.basename(path), os.path.getsize(path), flush=True)
    cache = cl.load_cache(path)
    chars = cache.get("characters") or {}
    memo = {}
    byhouse = {}
    for cid, rec in chars.items():
        if not isinstance(rec, dict):
            continue
        h = rec.get("dynasty_house")
        if h is None:
            continue
        byhouse.setdefault(str(h), []).append((cid, rec))
    out = []
    for hid, members in byhouse.items():
        names = [str(r.get("name_full") or "") + "|" + str(r.get("house_name") or "")
                 + "|" + str(r.get("dynasty_name") or "")
                 for _c, r in members]
        hit = [w for w in WANT if any(w in n for n in names)]
        if not hit:
            continue
        head = (cache.get("dynasties") or {}).get("dynasty_house", {}).get(str(hid), {})
        vote = cl._house_name_order(cache, {"dynasty_house": int(hid) if str(hid).isdigit()
                                            else hid}, None, memo=memo)
        out.append(f"== 房 {hid}  命中 {hit}  成员 {len(members)}  "
                   f"name_full 投票={vote!r}  家主/首领字段={ {k: head.get(k) for k in ('name','head_of_house','historical')} }")
        for cid, r in members[:14]:
            out.append("     %-10s name_zh=%-14s culture=%-18s name_full=%-18s order=%r"
                       % (cid, r.get("name_zh"), r.get("culture"),
                          r.get("name_full"), cl._name_full_order(r)))
    log = os.path.join(ROOT, "logs", f"v123_housetrad_{FOLDER}.txt")
    io.open(log, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("\n".join(out))
    print("已写", log)


if __name__ == "__main__":
    main()
