# -*- coding: utf-8 -*-
"""研究第三波: 周皇朝/李漼标题, 孙子头衔, 语言字段, 大事年表重复, 刺客块大小, 家族恩怨章节。"""
import json
import sys
import os
import re

sys.path.insert(0, r"D:\Roman")
import localization as L

CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
MELT931 = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"
MELT882 = r"D:\Roman\output\菲利普3\data\melt_882_01_01.json"
PROMPTS = r"D:\Roman\logs\prompts.log"
MD = r"D:\Roman\output\菲利普3\菲利普崔佛_终传_931_06_07.md"

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
    m931 = load(MELT931)
    lt931 = (m931.get("landed_titles") or {}).get("landed_titles") or {}
    chars931 = all_chars(m931)
    cm931 = (m931.get("culture_manager") or {}).get("cultures") or {}
    table = L.table()

    # ---- A) 周皇朝 本地化键 ----
    print("== A) 本地化含 周皇朝 的键 ==")
    for k, v in table.items():
        if "周皇" in str(v):
            print("   ", k, "=", v)

    # ---- B) 玩家 38725 在 931 的帝国头衔 ----
    print("\n== B) 玩家931持有头衔 (e_/h_级) ==")
    for tid, t in lt931.items():
        if not isinstance(t, dict):
            continue
        h = t.get("holder")
        if h == 38725:
            key = t.get("key") or ""
            tnd = t.get("title_name_data") or {}
            nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
            if not nm:
                nm = L.loc(table, key)
            print("   ", tid, key, "|", nm, "| name_data:", tnd)
    # 玩家主头衔: alive_data.primary_title?
    p931 = chars931.get("38725") or {}
    print("   玩家 alive_data keys:", list((p931.get("alive_data") or {}).keys())[:20])
    print("   玩家 landed_data domain:", (p931.get("landed_data") or {}).get("domain"))

    # ---- C) 李漼 搜索 ----
    print("\n== C) 李漼 字符搜索 (882 & 931) ==")
    for path, tag in ((MELT882, "882"), (MELT931, "931")):
        m = load(path)
        ch = all_chars(m)
        hits = []
        for cid, c in ch.items():
            fn = c.get("first_name") or ""
            if "漼" in fn or fn == "李漼":
                hits.append((cid, fn, c.get("dynasty_house")))
            # 也找 name_zh 可能含李漼
        print("   melt%s: %s" % (tag, hits[:10]))
    # 在缓存 characters 中找
    print("   缓存中 first_name 含漼:")
    for cid, rec in (cache.get("characters") or {}).items():
        fn = rec.get("name_zh") or rec.get("first_name") or ""
        if "漼" in str(fn):
            print("     ", cid, rec.get("name_zh"), rec.get("name_full"), rec.get("house_name"))

    # ---- D) 孙子 16836221 的头衔 14439.. ----
    print("\n== D) 孙子16836221 头衔 ==")
    for tid in (14439, 14446, 14440, 14447, 14441, 14443, 14449):
        t = lt931.get(str(tid)) or {}
        key = t.get("key") or ""
        tnd = t.get("title_name_data") or {}
        nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
        if not nm:
            nm = L.loc(table, key)
        print("   ", tid, key, "|", nm, "| holder:", t.get("holder"),
              "| liege:", t.get("de_facto_liege"))
    # k_qingxu 完整对象
    print("   k_qingxu(14109) 完整:", json.dumps(lt931.get("14109"), ensure_ascii=False)[:600])
    # 富兰克林 16820097 的 liege 14888 是什么
    t14888 = lt931.get("14888") or {}
    print("   14888:", t14888.get("key"), "| holder:", t14888.get("holder"),
          "| liege:", t14888.get("de_facto_liege"))
    # 孙子在 realm_history 中的持有
    print("   孙子在 realm_history 中持有:")
    cnt = 0
    for h in cache.get("realm_history") or []:
        for tid, holder in (h.get("holders") or {}).items():
            if holder == 16836221:
                t = lt931.get(str(tid)) or {}
                print("     ", h.get("date"), tid, t.get("key"))
                cnt += 1
        if cnt > 20:
            break

    # ---- E) 语言字段 ----
    print("\n== E) 语言字段 (melt931) ==")
    cnt = 0
    lang_sample = []
    for cid, c in chars931.items():
        for k in c.keys():
            if "lang" in k.lower():
                lang_sample.append((cid, k, c.get(k)))
                cnt += 1
        if cnt > 8:
            break
    print("   sample:", lang_sample)
    print("   melt 顶层键:", [k for k in m931.keys() if "lang" in k.lower()])
    total = sum(1 for c in chars931.values()
                for k in c.keys() if "lang" in k.lower())
    print("   角色含 lang 键字段总数:", total)

    # ---- F) prompts.log 中 大事年表 重复事件统计 ----
    print("\n== F) prompts.log 中【主角大事年表】块统计 ==")
    txt = None
    with open(PROMPTS, "r", encoding="utf-8") as fp:
        txt = fp.read()
    # 找第一处【主角大事年表】
    m = re.search(r"【主角大事年表】\n(.*?)(?:\n\n|\n  )", txt, re.S)
    if m:
        block = m.group(1)
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        print("   总行数:", len(lines))
        from collections import Counter
        dates = Counter()
        for l in lines:
            dm = re.match(r"^(\d+年\d+月\d+日)", l)
            if dm:
                dates[dm.group(1)] += 1
        print("   同日多条事件 top:")
        for d, n in dates.most_common(12):
            print("     ", d, n)
        # 见证加冕 行数
        coro = [l for l in lines if "见证加冕" in l]
        print("   见证加冕 行数:", len(coro))

    # ---- G) 刺客列传 prompt 块大小 + lowborn 明细 ----
    print("\n== G) 刀下诸魂 块 ==")
    m2 = re.search(r"刀下诸魂\n(.*?)(?:\n\n|\n  )", txt, re.S)
    if m2:
        block = m2.group(1)
        lines = [l for l in block.splitlines() if l.strip()]
        print("   块行数:", len(lines), "| 死者数:", lines.count("死者：") if False else sum(1 for l in lines if l.startswith("死者：")))
    # 低地出身者中: 有多少有 events/记忆
    kills = set((cache.get("characters") or {}).get(str(cache.get("player_id")) or "", {}).get("kills") or [])
    pd = cache.get("player_death") or {}
    kills |= set(pd.get("kills") or [])
    chars = cache.get("characters") or {}
    low = [cid for cid in kills if not (chars.get(str(cid)) or {}).get("house_name")]
    print("   lowborn kills:", len(low))
    for cid in low[:30]:
        rec = chars.get(str(cid)) or {}
        print("     ", cid, rec.get("name_zh"), "| mems:", len(rec.get("memories") or []),
              "| death:", bool(rec.get("death")), "| office? no field")

    # ---- H) 终传 md 各文章长度 ----
    print("\n== H) 终传 md 章节长度 ==")
    with open(MD, "r", encoding="utf-8") as fp:
        md = fp.read()
    parts = re.split(r"\n## ", md)
    for p in parts[1:]:
        title = p.split("\n")[0].strip()
        print("   ##", title, "| 字数:", len(p))

if __name__ == "__main__":
    main()
