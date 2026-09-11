# -*- coding: utf-8 -*-
"""马克龙十问：角色/记忆/关系/领地 逐一侦察（一次整载）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_macron_melt2.py
"""
import json
import os
import sys

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

MELT = r"D:\Roman\output\马克龙\data\melt_879_01_01.json"
OUT = os.path.join(ROOT, "tools", "out_macron")
PLAYER = 38677
WIFE = 38696  # 占位，脚本内再核


def dump(name, obj):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as fp:
        if isinstance(obj, str):
            fp.write(obj)
        else:
            json.dump(obj, fp, ensure_ascii=False, indent=1)
    print(f"  写入 {p}", flush=True)


def find_char(melt, cid):
    for bucket in ("living", "dead_unprunable", "dead_prunable",
                   "deleted_characters"):
        b = melt.get(bucket) or {}
        if str(cid) in b:
            return bucket, b[str(cid)]
    return None, None


def main():
    print(f"载入 {MELT} …", flush=True)
    melt = cl.load_melt(MELT)
    print("载入完成", flush=True)
    db = (melt.get("character_memory_manager") or {}).get("database") or {}

    bucket, p = find_char(melt, PLAYER)
    fam = (p or {}).get("family_data") or {}
    wife = fam.get("primary_spouse") or fam.get("spouse")
    if isinstance(wife, list):
        wife = wife[0]
    print(f"玩家在 {bucket}; 配偶 id={wife}", flush=True)
    dump("player_family_data.json", fam)

    # ---- 关系网（牵制）----
    rel = melt.get("relations") or {}
    dump("relations_top_keys.json", sorted(rel.keys()) if isinstance(rel, dict) else str(type(rel)))
    ar = rel.get("active_relations") if isinstance(rel, dict) else None
    print(f"active_relations 类型={type(ar).__name__} 长度={len(ar) if hasattr(ar,'__len__') else '?'}", flush=True)
    if isinstance(ar, list) and ar:
        dump("relations_sample.json", ar[:6])
    # 与玩家/配偶相关的关系
    def ids_of(entry):
        out = set()
        if isinstance(entry, dict):
            for k, v in entry.items():
                if "hook" in str(k).lower():
                    continue
                if isinstance(v, int):
                    out.add(v)
                elif isinstance(v, dict):
                    for kk in ("first", "second", "character", "target", "source"):
                        if isinstance(v.get(kk), int):
                            out.add(v[kk])
        return out

    inter = []
    if isinstance(ar, list):
        for e in ar:
            if not isinstance(e, dict):
                continue
            ids = ids_of(e)
            if PLAYER in ids or wife in ids:
                inter.append(e)
    dump("relations_player_wife.json", inter)
    print(f"涉及玩家/配偶的关系 {len(inter)} 条", flush=True)

    # ---- 配偶记忆 ----
    wb, w = find_char(melt, wife)
    print(f"配偶在 {wb}", flush=True)
    if w:
        mid_list = cl.mem_ids_of(w)
        mems = []
        for mid in mid_list:
            e = db.get(str(mid))
            if isinstance(e, dict):
                mems.append({"id": mid, "type": e.get("type"),
                             "creation_date": e.get("creation_date"),
                             "participants": e.get("participants"),
                             "variables": e.get("variables")})
        mems.sort(key=lambda m: str(m.get("creation_date")))
        dump("wife_memories.json", mems)
        dump("wife_raw.json", {k: v for k, v in w.items() if k != "memories"})
        print(f"配偶记忆 {len(mems)} 条", flush=True)

    # ---- 玩家记忆 ----
    pmid_list = cl.mem_ids_of(p)
    pmems = []
    for mid in pmid_list:
        e = db.get(str(mid))
        if isinstance(e, dict):
            pmems.append({"id": mid, "type": e.get("type"),
                          "creation_date": e.get("creation_date"),
                          "participants": e.get("participants"),
                          "variables": e.get("variables")})
    pmems.sort(key=lambda m: str(m.get("creation_date")))
    dump("player_memories.json", pmems)
    print(f"玩家记忆 {len(pmems)} 条", flush=True)

    # ---- 玩家领地 ----
    ld = (p or {}).get("landed_data") or {}
    lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}
    dom = ld.get("domain") or []
    tinfo = {}
    for tid in dom:
        t = lt.get(str(tid)) or {}
        tinfo[str(tid)] = {"key": t.get("key"), "tier": t.get("tier"),
                           "de_facto_liege": t.get("de_facto_liege"),
                           "de_jure_liege": t.get("de_jure_liege"),
                           "capital": t.get("capital"),
                           "capital_key": (lt.get(str(t.get("capital"))) or {}).get("key"),
                           "history_len": len(t.get("history") or [])}
    dump("player_domain_titles.json", {"domain": dom, "titles": tinfo,
                                       "realm_capital": ld.get("realm_capital"),
                                       "vassal_contracts": ld.get("vassal_contracts"),
                                       "government": ld.get("government")})
    print("领地已导出", flush=True)

    # ---- 名字搜索: 乔乔 ----
    import localization as L
    try:
        cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    table = L.load_localization_table(cfg) if hasattr(L, "load_localization_table") else {}

    def look_name(cid):
        b, c = find_char(melt, cid)
        if not c:
            return {"id": cid, "bucket": None}
        nm = c.get("name")
        first = c.get("first_name") or ""
        out = {"id": cid, "bucket": b, "name": nm, "first_name": first,
               "birth": c.get("birth"), "death": c.get("death"),
               "dynasty_house": c.get("dynasty_house"),
               "culture": c.get("culture"), "faith": c.get("faith"),
               "traits": c.get("traits"),
               "alive_data_keys": sorted((c.get("alive_data") or {}).keys()),
               "dead_data": c.get("dead_data"),
               "nickname_text": c.get("nickname_text")}
        return out

    # 从配偶记忆里找 869.9.8 had_sex 的对方 id
    cands = {}
    for m in (mems if w else []):
        if str(m.get("creation_date", "")).startswith("869.9.8") and \
                m.get("type") in ("had_sex", "became_lovers", "became_soulmates"):
            cands[str(m["id"])] = m
    dump("wife_869_09_08.json", cands)
    ids = set()
    for m in (mems if w else []):
        for v in (m.get("participants") or {}).values():
            if isinstance(v, int):
                ids.add(v)
    dump("wife_partner_profiles.json", {str(i): look_name(i) for i in sorted(ids)})
    print("名字/对象已导出", flush=True)


if __name__ == "__main__":
    sys.exit(main())
