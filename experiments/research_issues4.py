# -*- coding: utf-8 -*-
"""研究第四波: 历任重建可行性(title history), 恩仇候选记忆数, 家族恩怨数据, 语言原始扫描, 被杀的家人。"""
import json
import sys
import re

sys.path.insert(0, r"D:\Roman")
import localization as L

CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
MELT931 = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"
MELT882 = r"D:\Roman\output\菲利普3\data\melt_882_01_01.json"

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
    table = L.table()
    pid = cache.get("player_id")

    # ---- 1) 历任重建: 玩家 38725 在各头衔 title.history 中的任职 ----
    print("== 1) 玩家 %s 在 title.history 中的任职 (melt931) ==" % pid)
    rows = []
    for tid, t in lt931.items():
        if not isinstance(t, dict):
            continue
        hist = t.get("history") or {}
        if not isinstance(hist, dict):
            continue
        for d, ev in hist.items():
            if isinstance(ev, dict):
                h = ev.get("holder")
            else:
                h = ev
            if h == pid:
                key = t.get("key") or ""
                tnd = t.get("title_name_data") or {}
                nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
                if not nm:
                    nm = L.loc(table, key)
                rows.append((d, tid, key, nm, ev if isinstance(ev, dict) else ""))
    rows.sort(key=lambda x: (int(x[0].split(".")[0]) if x[0] else 0))
    print("   玩家任职记录数:", len(rows))
    for r in rows[:40]:
        print("   ", r)

    # ---- 2) k_qingxu 完整 history (尾部) ----
    print("\n== 2) k_qingxu history (最近 12 条) ==")
    kq = lt931.get("14109") or {}
    hist = kq.get("history") or {}
    items = sorted(hist.items(), key=lambda x: x[0])
    for d, ev in items[-12:]:
        print("   ", d, ev)

    # ---- 3) 恩仇候选: 各仇人记忆数 ----
    print("\n== 3) 与玩家结仇者的记忆数 ==")
    enemy_mem_types = {"became_rivals", "became_grudge", "became_nemesis"}
    enemies = {}
    for cid, rec in (cache.get("characters") or {}).items():
        for mem in rec.get("memories") or []:
            if mem.get("type") in enemy_mem_types:
                parts = mem.get("participants") or {}
                if pid in parts.values():
                    enemies.setdefault(int(cid), []).append(mem.get("creation_date"))
    out = []
    for cid, dates in enemies.items():
        rec = (cache.get("characters") or {}).get(str(cid)) or {}
        out.append((min(dates), cid, rec.get("name_zh"),
                    len(rec.get("memories") or []),
                    len(dates)))
    out.sort()
    print("   仇人 (最早结仇日期, id, 名, 总记忆数, 结仇记忆数):")
    for r in out:
        print("   ", r)
    # 卡托内
    print("   卡托内 id:", [x for x in out if x[2] == "卡托内"])
    # 记忆数>5 的仇人
    rich = [x for x in out if x[3] > 5]
    print("   记忆>5 的仇人:", rich)

    # ---- 4) 家族恩怨 (house_feuds 数据源) ----
    print("\n== 4) 与玩家家族负面关系的家族 (melt931 house_relations) ==")
    prec = (cache.get("characters") or {}).get(str(pid)) or {}
    my_houses = set()
    h0 = prec.get("dynasty_house")
    if isinstance(h0, int):
        my_houses.add(h0)
    did = cache.get("dynasty_id")
    dh = (m931.get("dynasties") or {}).get("dynasty_house") or {}
    if did is not None:
        for hid, e in dh.items():
            if isinstance(e, dict) and e.get("dynasty") == did:
                my_houses.add(int(hid))
    hr = (m931.get("house_relations") or {}).get("database") or {}
    NEG = {"default_house_relation_level_feud",
           "default_house_relation_level_rivalry",
           "default_house_relation_level_quarrel"}
    print("   我的 house:", my_houses)
    for k, r in hr.items():
        if not isinstance(r, dict):
            continue
        hs = r.get("houses") or []
        if not any(h in my_houses for h in hs):
            continue
        if (r.get("level") or "") not in NEG:
            continue
        other = [h for h in hs if h not in my_houses]
        hist = r.get("history") or []
        names = []
        for h in other:
            hn = ""
            for hid, e in dh.items():
                if int(hid) == h:
                    hn = (e or {}).get("name") or str(h)
            names.append(hn)
        print("   关系:", r.get("level"), "| 对方:", names, "| history条数:", len(hist))
        for e in hist[:6]:
            txt = str(e.get("change_reason") or "")
            print("       ", e.get("date"), txt[:60])

    # ---- 5) 被杀的家人 33592286 ----
    print("\n== 5) 被杀的家人 33592286 ==")
    rec = (cache.get("characters") or {}).get("33592286") or {}
    print("   name_zh:", rec.get("name_zh"), "| house:", rec.get("house_name"),
          "| death:", rec.get("death"), "| mems:", len(rec.get("memories") or []))

    # ---- 6) 语言: 原始文本扫描 ----
    print("\n== 6) 原始文本 language 扫描 ==")
    for path, tag in ((MELT882, "882"), (MELT931, "931")):
        cnt = 0
        sample = []
        with open(path, "r", encoding="utf-8") as fp:
            chunk = fp.read(64 * 1024 * 1024)  # 64MB 前部
        for m in re.finditer(r'"(languages?|spoken_languages?|langs?)"\s*:', chunk):
            cnt += 1
            if len(sample) < 3:
                sample.append(chunk[max(0, m.start() - 80):m.start() + 120])
        print("   melt%s: 匹配 %d 处" % (tag, cnt), sample[:1])

if __name__ == "__main__":
    main()
