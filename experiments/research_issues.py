# -*- coding: utf-8 -*-
"""研究 11 个问题: 只读分析, 不改任何数据。
用法: python experiments/research_issues.py [cache_json]
"""
import json
import os
import sys

CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
MELT882 = r"D:\Roman\output\菲利普3\data\melt_882_01_01.json"
MELT931 = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"

def load(path):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)

def main():
    cache = load(CACHE)
    print("== cache keys ==", list(cache.keys()))
    print("== player ==", cache.get("player_id"), cache.get("player_name"),
          cache.get("house_name"), "sources", len(cache.get("sources") or []),
          "last", cache.get("last_date"))
    pd = cache.get("player_death") or {}
    print("== player_death ==", {k: v for k, v in pd.items() if k != "kills"},
          "| kills:", len(pd.get("kills") or []))

    # ---- realm_history: 找 周皇朝 / 李漼 ----
    rh = cache.get("realm_history") or []
    print("\n== realm_history len ==", len(rh))
    # 先看 882 档 holders 的 title->holder 里哪些 title 在 melt 里 key 是什么
    melt = load(MELT882)
    lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}
    loc_table = None
    try:
        import localization as L
        loc_table = L.table()
    except Exception as e:
        print("loc import fail", e)

    # 反查: 李漼 的角色 id
    chars882 = {}
    for cid, c in (melt.get("living") or {}).items():
        if isinstance(c, dict):
            chars882[cid] = c
    for cid, c in (melt.get("dead_unprunable") or {}).items():
        if isinstance(c, dict):
            chars882.setdefault(cid, c)
    for cid, c in (melt.get("dead_prunable") or {}).items():
        if isinstance(c, dict):
            chars882.setdefault(cid, c)
    li_cui = [cid for cid, c in chars882.items()
              if (c.get("first_name") or "").strip() == "李漼"]
    print("== 李漼 ids in melt882 ==", li_cui[:10])
    # first_name 可能为空, 用 name_zh 或信封? 直接找 name 字段
    li2 = [cid for cid, c in chars882.items()
           if "李漼" in json.dumps({k: c.get(k) for k in ("first_name",)}, ensure_ascii=False)]
    print("  (json-scan) 李漼 ids ==", li2[:10])

    # 找出熔件中 name/自定义名 == 周皇朝 的头衔
    zhou_titles = []
    for tid, t in lt.items():
        if not isinstance(t, dict):
            continue
        tnd = t.get("title_name_data") or {}
        nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
        if nm == "周皇朝" or (t.get("key") or "") == "h_zhou":
            zhou_titles.append((tid, t.get("key"), nm))
    print("== 周皇朝 titles in melt882 ==", zhou_titles[:20])

    # realm_history 中 holder 为 李漼 id 的 title 随时间
    if li_cui:
        cid_li = li_cui[0]
        print("\n== realm_history rows where 李漼 is holder ==")
        for h in rh:
            for tid, holder in (h.get("holders") or {}).items():
                if holder == cid_li:
                    print("  ", h.get("date"), "title_tid=", tid,
                          "key=", (lt.get(str(tid)) or {}).get("key"))
    # 每个快照里 周皇朝 title 的 holder 序列
    if zhou_titles:
        ztid = zhou_titles[0][0]
        seq = []
        for h in rh:
            hh = (h.get("holders") or {}).get(ztid)
            if hh is not None:
                seq.append((h.get("date"), hh))
        print("\n== 周皇朝(tid=%s) holder seq ==" % ztid)
        for d, hh in seq[:60]:
            print("  ", d, hh)

    # ---- kills: 低地出身统计 ----
    prec = (cache.get("characters") or {}).get(str(cache.get("player_id"))) or {}
    kills = set(prec.get("kills") or []) | set((pd.get("kills") or []))
    print("\n== kills total ==", len(kills))
    chars = cache.get("characters") or {}
    lowborn = [cid for cid in kills if not ((chars.get(str(cid)) or {}).get("house_name"))]
    with_house = [cid for cid in kills if (chars.get(str(cid)) or {}).get("house_name")]
    print("  lowborn(no house):", len(lowborn), "| with house:", len(with_house))
    fam = prec.get("family") or {}
    fam_ids = set()
    for k in ("primary_spouse", "spouse", "former_spouses", "child", "concubine", "former_concubines"):
        for x in fam.get(k) or []:
            fam_ids.add(int(x))
    in_fam = [cid for cid in kills if cid in fam_ids]
    print("  killed who are family:", len(in_fam), in_fam[:20])

    # ---- 富兰克林之子 (菲利普崔佛) 名字 ----
    print("\n== 富兰克林 children (cache) ==")
    for cid, rec in chars.items():
        if rec.get("name_zh") == "富兰克林":
            print("  father id", cid, "children:",
                  [(c, (chars.get(str(c)) or {}).get("name_zh"),
                    (chars.get(str(c)) or {}).get("name_full"))
                   for c in (rec.get("family") or {}).get("child") or []])
            print("  house_name:", rec.get("house_name"), "culture:", rec.get("culture"))
            break

    # ---- feuds 数据量 ----
    print("\n== house_relations (melt931) 负面家族 ==")
    melt931 = load(MELT931)
    hr = (melt931.get("house_relations") or {}).get("database") or {}
    print("  total house_relations:", len(hr))
    for k, r in hr.items():
        if not isinstance(r, dict):
            continue
        lvl = r.get("level") or ""
        if "feud" in str(lvl) or "rivalry" in str(lvl) or "quarrel" in str(lvl):
            print("  ", k, lvl, "houses:", r.get("houses"), "history:", len(r.get("history") or []))

    # ---- language 数据是否存在 ----
    print("\n== language fields in melt882 ==")
    cnt = 0
    sample = []
    for cid, c in chars882.items():
        for k in c.keys():
            if "lang" in k.lower():
                sample.append((cid, k, c.get(k)))
                cnt += 1
                if cnt > 5:
                    break
        if cnt > 5:
            break
    print("  sample:", sample)
    print("  top-level melt keys with 'lang':",
          [k for k in melt.keys() if "lang" in k.lower()])
    # 全量计数
    total = 0
    for cid, c in chars882.items():
        total += sum(1 for k in c.keys() if "lang" in k.lower())
    print("  chars with lang-key fields:", total)

if __name__ == "__main__":
    main()
