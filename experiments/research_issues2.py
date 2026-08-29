# -*- coding: utf-8 -*-
"""研究 11 个问题 (第二波): 名字/文化/头衔/周皇朝/死因本地化。只读。"""
import json
import sys
import os

sys.path.insert(0, r"D:\Roman")
import localization as L

CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
MELT882 = r"D:\Roman\output\菲利普3\data\melt_882_01_01.json"
MELT931 = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"

def load(path):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)

def all_chars(melt):
    out = {}
    for sec in ("living", "dead_unprunable", "dead_prunable"):
        for cid, c in (melt.get(sec) or {}).items():
            if isinstance(c, dict):
                out.setdefault(cid, c)
    return out

def main():
    cache = load(CACHE)
    lt931 = (load(MELT931).get("landed_titles") or {}).get("landed_titles") or {}
    chars931 = all_chars(load(MELT931))
    cm931 = (load(MELT931).get("culture_manager") or {}).get("cultures") or {}
    table = L.table()

    # ---- 1) 孙子 16836221 / 富兰克林 16820097 ----
    print("== 孙子 16836221 (melt931) ==")
    g = chars931.get("16836221") or {}
    print("  first_name:", g.get("first_name"), "| culture:", g.get("culture"),
          "| dynasty_house:", g.get("dynasty_house"), "| female:", g.get("female"))
    fd = g.get("family_data") or {}
    print("  family father/mother:", fd.get("father"), fd.get("mother"))
    ld = g.get("landed_data") or {}
    print("  domain:", ld.get("domain"))
    gd = g.get("dead_data") or {}
    print("  dead?", bool(gd), gd.get("date"))
    gid = g.get("culture")
    if gid is not None:
        e = cm931.get(str(gid)) or {}
        print("  culture template:", e.get("culture_template"),
              "| name_order:", e.get("name_order_convention"),
              "| loc:", L.loc(table, e.get("culture_template") or ""))
    print("\n== 富兰克林 16820097 (melt931) ==")
    f = chars931.get("16820097") or {}
    print("  first_name:", f.get("first_name"), "| culture:", f.get("culture"))
    fld = f.get("landed_data") or {}
    print("  domain:", fld.get("domain"))
    fdead = f.get("dead_data") or {}
    print("  dead?", bool(fdead), fdead.get("date"))
    # 富兰克林各年 domain 演变 (用缓存 realm_history 里 他作为 holder 的 title)
    print("\n== 富兰克林在 realm_history 中的持有 ==")
    for h in cache.get("realm_history") or []:
        for tid, holder in (h.get("holders") or {}).items():
            if holder == 16820097:
                t = lt931.get(str(tid)) or {}
                print("   ", h.get("date"), tid, t.get("key"))

    # ---- 2) 青徐 头衔 ----
    print("\n== 含「青徐」的头衔 (melt931) ==")
    for tid, t in lt931.items():
        if not isinstance(t, dict):
            continue
        tnd = t.get("title_name_data") or {}
        nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
        if "青徐" in nm or "青徐" in (t.get("key") or ""):
            print("  ", tid, t.get("key"), nm, "holder:", t.get("holder"))
    # 看 k_qingxu 等近邻 key
    for tid, t in lt931.items():
        if not isinstance(t, dict):
            continue
        k = t.get("key") or ""
        if k in ("k_qingxu", "d_ziqing", "k_qing", "d_qingxu"):
            tnd = t.get("title_name_data") or {}
            nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
            print("  candidate:", tid, k, nm, "holder:", t.get("holder"),
                  "liege:", t.get("de_facto_liege"))

    # ---- 3) 周皇朝 / 李漼 溯源 ----
    print("\n== 周皇朝标题溯源 (melt931 / melt882) ==")
    for path, tag in ((MELT882, "882"), (MELT931, "931")):
        m = load(path)
        lt = (m.get("landed_titles") or {}).get("landed_titles") or {}
        found = []
        for tid, t in lt.items():
            if not isinstance(t, dict):
                continue
            tnd = t.get("title_name_data") or {}
            nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
            if not nm:
                nm = L.loc(table, t.get("key") or "")
            if "周皇" in nm or "唐皇" in nm:
                found.append((tid, t.get("key"), nm, t.get("holder")))
        print("  melt%s: %s" % (tag, found[:10]))
    # 882 档中玩家所在帝国的头衔: 玩家 38725 的上位链
    m882 = load(MELT882)
    lt882 = (m882.get("landed_titles") or {}).get("landed_titles") or {}
    p = all_chars(m882).get("38725") or {}
    print("  玩家882: first_name", p.get("first_name"), "domain:", (p.get("landed_data") or {}).get("domain"))
    # 找 holder == 玩家 的头衔 & 玩家主头衔的 de_facto_liege 链
    seen = set()
    cur = (p.get("landed_data") or {}).get("domain") or []
    chain = []
    stack = list(cur)
    while stack and len(chain) < 8:
        tid = str(stack.pop(0))
        if tid in seen:
            continue
        seen.add(tid)
        t = lt882.get(tid) or {}
        if not t:
            continue
        key = t.get("key") or ""
        tnd = t.get("title_name_data") or {}
        nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip() or L.loc(table, key)
        holder = t.get("holder")
        hn = ""
        c = all_chars(m882).get(str(holder)) if holder is not None else None
        if c:
            hn = (c.get("first_name") or "") + "/" + str(holder)
        chain.append((tid, key, nm, holder, hn))
        l = t.get("de_facto_liege")
        if l is not None:
            stack.append(l)
    print("  玩家882上位链:")
    for row in chain:
        print("    ", row)

    # ---- 4) 死因 blind 本地化 ----
    print("\n== 死因 'blind' 本地化 ==")
    for k in ("blind", "death_blind", "death_accident"):
        v = L.loc(table, k)
        print("  ", k, "->", repr(v))
    # 在 localization.json 中找含「绊倒」的键
    print("  含「绊倒」的本地化键:")
    cnt = 0
    for k, v in table.items():
        if "绊倒" in str(v):
            print("    ", k, "=", v)
            cnt += 1
            if cnt > 12:
                break
    # culture 诺斯 本地化
    print("\n== culture_template 诺斯 ==")
    for k, v in table.items():
        if v == "诺斯" or "Norse" in k:
            print("    ", k, "=", v)
            break
    # 检查 "失去的生命" 类似的键 (其他怪死因)
    print("  含「失去的生命」/「生命」的本地化键:")
    cnt = 0
    for k, v in table.items():
        if "失去的生命" in str(v) or ("的生命" in str(v) and "失去" in str(v)):
            print("    ", k, "=", v)
            cnt += 1
            if cnt > 10:
                break

if __name__ == "__main__":
    main()
