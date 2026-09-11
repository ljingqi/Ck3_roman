# -*- coding: utf-8 -*-
"""马克龙十问：批次 B —— 领地层级 / 乔乔处境 / 牵制全量 / 文化。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_macron_melt3.py
"""
import json
import os
import sys

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

MELT = r"D:\Roman\output\马克龙\data\melt_879_01_01.json"
OUT = os.path.join(ROOT, "tools", "out_macron")
PID = 38677
WIFE = 15682
JOJO = 43961
DOMAIN = [7472, 7469, 7464, 7473, 7470, 7465]


def dump(name, obj):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=1)
    print(f"  写入 {p}", flush=True)


def main():
    print(f"载入 {MELT} …", flush=True)
    melt = cl.load_melt(MELT)
    print("载入完成", flush=True)
    lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}

    # ---- 领地原始对象 ----
    raw = {}
    for tid in DOMAIN:
        t = lt.get(str(tid)) or {}
        raw[str(tid)] = {k: v for k, v in t.items() if k != "history"}
    # 大写父级链上的头衔 (伯爵领/公国)
    for tid in DOMAIN:
        t = lt.get(str(tid)) or {}
        for lk in ("de_jure_liege", "de_facto_liege"):
            p = t.get(lk)
            if isinstance(p, int) and str(p) not in raw:
                pt = lt.get(str(p)) or {}
                raw[str(p)] = {k: v for k, v in pt.items() if k != "history"}
    dump("landed_titles_raw.json", raw)

    # 所有以 c_bearn/c_bigorre/c_armagnac 为 de_jure_liege 的男爵领
    kids = {}
    for tid, t in lt.items():
        if not isinstance(t, dict):
            continue
        if t.get("de_jure_liege") in DOMAIN or t.get("capital") in DOMAIN:
            kids[str(tid)] = {"key": t.get("key"), "de_jure_liege": t.get("de_jure_liege"),
                              "capital": t.get("capital"), "province": t.get("province")}
    dump("landed_titles_kids.json", kids)

    # ---- holdings / provinces ----
    hold = melt.get("holdings") or {}
    dump("holdings_keys.json", sorted(hold.keys()) if isinstance(hold, dict) else str(type(hold)))
    if isinstance(hold, dict):
        db = hold.get("holdings") or hold.get("database") or hold
        dumped = {}
        if isinstance(db, dict):
            for hid, h in list(db.items()):
                if isinstance(h, dict) and (h.get("title") in DOMAIN
                                            or h.get("province") in (2193, 2010)):
                    dumped[str(hid)] = h
        dump("holdings_of_domain.json", dumped)
    prov = melt.get("provinces") or {}
    if isinstance(prov, dict):
        pd = prov.get("provinces") or {}
        dump("provinces_of_domain.json",
             {k: v for k, v in pd.items() if str(k) in ("2193", "2010", "2194", "2011")})

    # ---- 乔乔处境 ----
    chars = melt.get("living") or {}
    j = chars.get(str(JOJO)) or {}
    dump("jojo_alive.json", j)
    cp = (melt.get("court_positions") or {}).get("database") or {}
    dump("court_positions_keys.json", sorted(cp.keys())[:30] if isinstance(cp, dict) else str(type(cp)))
    jpos = []
    if isinstance(cp, dict):
        for pid, e in cp.items():
            if not isinstance(e, dict):
                continue
            if e.get("employee") == JOJO or JOJO in (e.get("employees") or []):
                jpos.append({"id": pid, "entry": e})
    dump("jojo_court_positions.json", jpos)

    # ---- 谁持有记忆 15660 / 是否重复 ----
    owners = {}
    for bucket in ("living", "dead_unprunable", "dead_prunable"):
        for cid, c in (melt.get(bucket) or {}).items():
            if not isinstance(c, dict):
                continue
            ids = set(str(x) for x in (cl.mem_ids_of(c) or []))
            for mid in ("15658", "15660", "16439", "16106", "16105", "16784085"):
                if mid in ids:
                    owners.setdefault(mid, []).append({"cid": cid, "bucket": bucket})
    dump("memory_owners.json", owners)

    # ---- 文化 0 / language_kwa ----
    cm = (melt.get("culture_manager") or {}).get("cultures") or {}
    dump("culture_0.json", cm.get("0") or cm.get(0) or {})
    dump("culture_keys_sample.json", sorted(cm.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)[:8])

    # ---- 牵制全量 (relations.active_relations) ----
    ar = (melt.get("relations") or {}).get("active_relations") or []
    hooks = []
    for e in ar:
        if not isinstance(e, dict):
            continue
        f_, s_ = e.get("first"), e.get("second")
        for k, v in e.items():
            if str(k).startswith("active_hook") and isinstance(v, dict):
                hooks.append({"holder": f_, "target": s_, "type": v.get("type"),
                              "expiration": v.get("expiration_date")})
    dump("all_hooks.json", hooks)
    mine = [h for h in hooks if h["holder"] == PID]
    over_me = [h for h in hooks if h["target"] == PID]
    dump("hooks_mine.json", mine)
    dump("hooks_over_me.json", over_me)
    print(f"全档牵制 {len(hooks)} 条; 主角握有 {len(mine)}; 针对主角 {len(over_me)}", flush=True)

    # 牵制目标的姓名 (缓存外的角色名解析: 用 melt 的 first_name)
    def nm(cid):
        for bucket in ("living", "dead_unprunable", "dead_prunable"):
            c = (melt.get(bucket) or {}).get(str(cid))
            if isinstance(c, dict):
                return c.get("first_name") or c.get("name")
        return None
    dump("hooks_named.json", [dict(h, holder_name=nm(h["holder"]),
                                   target_name=nm(h["target"])) for h in hooks
                              if h["holder"] == PID or h["target"] == PID])


if __name__ == "__main__":
    sys.exit(main())
