# -*- coding: utf-8 -*-
"""v37 (问题8)：为既有缓存补起义领袖的 `base`（起事州府）。

背景：起义头衔（`x_script_*`「农民叛乱」等）带 `capital`（起事州府）、`date`（起事日）
与 `holder`（领袖），但 `delete_on_destroy = true` —— 领袖死后该头衔即从存档消失。
因此老缓存（建于 v37 之前）里没有 base；本脚本按其卒日/首见档扫**时代熔件**补上。

只补 `cache["factions"][cid]["base"]`（必要时新建该 leader 的 factions 条目），
其余缓存字段一概不动。

用法：
    & tools\\py.ps1 tools\\refresh_uprising_bases.py <家族文件夹> <玩家id> [--all]

做法（省时口径）：不解析 JSON —— 直接在熔件原文里找 `"<title_id>":{"key":"x_script_`
片段并截取后续 ~700 字符，正则取 holder/capital/date/name；一份熔件读一遍即可，
比整载快两个数量级。候选头衔 id 取缓存里该角色的 `death.liege_title`/`named_title`
（起义头衔即其「假头衔」）与已在 factions 里但缺 base 者。
`--all` 时也扫所有 factions 领袖（含无卒日者，用最新熔件）。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl          # noqa: E402

_WINDOW = 700
_KEY_RE = re.compile(r'"key":"(x_(?:script|mc|ho)_[^"]*)"')
_HOLDER_RE = re.compile(r'"holder":(\d+)')
_CAP_RE = re.compile(r'"capital":(\d+)')
_DATE_RE = re.compile(r'"date":"([\d.]+)"')
_NAME_RE = re.compile(r'"title_name_data":\{"name":"([^"]*)"')


def _melt_titles(path, tids):
    """在熔件原文里找若干头衔 id 的条目片段 → {tid: 片段}。"""
    raw = open(path, encoding="utf-8", errors="replace").read()
    out = {}
    for tid in tids:
        i = raw.find(f'"{tid}":{{"key":"x_')
        if i < 0:
            continue
        out[tid] = raw[i:i + _WINDOW]
    return out


def _parse(snippet):
    k = _KEY_RE.search(snippet)
    h = _HOLDER_RE.search(snippet)
    c = _CAP_RE.search(snippet)
    d = _DATE_RE.search(snippet)
    n = _NAME_RE.search(snippet)
    if not (k and h):
        return None
    return {"key": k.group(1), "holder": int(h.group(1)),
            "county": int(c.group(1)) if c else None,
            "from": d.group(1) if d else None,
            "name": n.group(1) if n else ""}


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_all = "--all" in sys.argv
    if len(argv) < 2:
        print(__doc__)
        return 2
    folder, pid = argv[0], int(argv[1])
    data = os.path.join(ROOT, "output", folder, "data")
    cache_path = os.path.join(data, f"player_{pid}.json")
    cache = json.load(open(cache_path, encoding="utf-8"))
    chars = cache.get("characters") or {}
    facs = cache.setdefault("factions", {})
    last = cache.get("last_date") or "9999.9.9"
    melts = sorted((x for x in os.listdir(data)
                    if x.startswith("melt_") and "_idx" not in x
                    and x.endswith(".json")),
                   key=lambda x: cl.date_key(x[5:-5].replace("_", ".")))
    melts = [m for m in melts if cl.date_key(m[5:-5].replace("_", "."))
             <= cl.date_key(last)]
    if not melts:
        print("找不到熔件")
        return 2
    latest = melts[-1]

    # 候选: (cid, 需要的头衔 id 候选, 说明)
    cands = []
    for cid, rec in facs.items():
        if rec.get("base"):
            continue
        r = chars.get(str(cid)) or {}
        d = (r.get("death") or {})
        tids = [t for t in (d.get("liege_title"), d.get("named_title"))
                if isinstance(t, int)]
        if tids or do_all:
            cands.append((cid, tids, d.get("date") or ""))
    if do_all:      # 也把「有卒日但无 factions 条目」的角色纳入 (王伯玉/张知微)
        for cid, r in chars.items():
            d = r.get("death") or {}
            if not d.get("date") or str(cid) in facs:
                continue
            tids = [t for t in (d.get("liege_title"), d.get("named_title"))
                    if isinstance(t, int)]
            if tids:
                cands.append((cid, tids, d.get("date") or ""))
    print(f"候选 {len(cands)} 人；熔件 {len(melts)} 份 (≤{last})")

    # 逐熔件扫（一份读一遍）: 先按需要它的候选挑熔件
    by_tid = {}
    for cid, tids, ddate in cands:
        for t in tids:
            by_tid.setdefault(str(t), []).append((cid, ddate))
    done = set()
    for name in melts:
        need = [t for t in by_tid if t not in done]
        if not need:
            break
        found = _melt_titles(os.path.join(data, name), need)
        if not found:
            continue
        for tid, snip in found.items():
            info = _parse(snip)
            if not info:
                continue
            cid = str(info["holder"])
            r = facs.setdefault(cid, {})
            r.setdefault("type", cl._UPRISING_TITLE_NAMES.get(info["name"],
                                                              "peasant_faction"))
            cname = ""
            # 州府名从同一份熔件原文里取（capital 指向 c_ 头衔）
            raw = open(os.path.join(data, name), encoding="utf-8",
                       errors="replace").read()
            j = raw.find(f'"{info["county"]}":{{"key":"c_')
            if j >= 0:
                m = _NAME_RE.search(raw[j:j + _WINDOW])
                cname = m.group(1) if m else ""
            r["base"] = {"title": int(tid), "county": info["county"],
                         "county_name": cname, "name": info["name"],
                         "from": info["from"], "type": r["type"]}
            r.setdefault("first_seen", info["from"] or name[5:-5].replace("_", "."))
            r.setdefault("last_seen", name[5:-5].replace("_", "."))
            done.add(tid)
            print(f"  {cid}: {info['name']} @{cname} (起事 {info['from']}, 出自 {name})")
    # 仍缺 base 者: 用最新熔件按 holder 反查
    missing = [c for c, r in facs.items() if not r.get("base")]
    if missing:
        raw = open(os.path.join(data, latest), encoding="utf-8",
                   errors="replace").read()
        for cid in missing:
            for m in re.finditer(r'"(\d+)":\{"key":"(x_(?:script|mc|ho)_[^"]*)"',
                                 raw):
                snip = raw[m.start():m.start() + _WINDOW]
                info = _parse(snip)
                if info and str(info["holder"]) == cid:
                    cname = ""
                    j = raw.find(f'"{info["county"]}":{{"key":"c_')
                    if j >= 0:
                        mm = _NAME_RE.search(raw[j:j + _WINDOW])
                        cname = mm.group(1) if mm else ""
                    facs[cid]["base"] = {"title": int(m.group(1)),
                                         "county": info["county"],
                                         "county_name": cname,
                                         "name": info["name"],
                                         "from": info["from"],
                                         "type": facs[cid].get("type", "peasant_faction")}
                    print(f"  {cid}: 最新档反查 {info['name']} @{cname}")
                    break
    have = [c for c, r in facs.items() if r.get("base")]
    print(f"补得 base: {len(have)} 人 / factions {len(facs)} 条")
    for cid in sorted(have, key=lambda x: int(x)):
        b = facs[cid]["base"]
        print(f"   {cid} {chars.get(cid, {}).get('name_full', '?')}: "
              f"{b.get('county_name') or b.get('county')} ({b.get('from')})")
    bak = cache_path + ".bak-v37"
    if not os.path.exists(bak):
        with open(bak, "w", encoding="utf-8") as fp:
            json.dump(json.load(open(cache_path, encoding="utf-8")), fp,
                      ensure_ascii=False)
        print(f"已备份原缓存 → {os.path.basename(bak)}")
    with open(cache_path, "w", encoding="utf-8") as fp:
        json.dump(cache, fp, ensure_ascii=False)
    print("已写入缓存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
