# -*- coding: utf-8 -*-
"""研究第五波: 语言本地化, 路岩/杨玄翼, 家族恩怨录/刺客列传正文, 孙子 alive_data, 王子词。"""
import json
import sys
import re

sys.path.insert(0, r"D:\Roman")
import localization as L

MELT931 = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"
PROMPTS = r"D:\Roman\logs\prompts.log"
MD = r"D:\Roman\output\菲利普3\菲利普崔佛_终传_931_06_07.md"
CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"

def load(path):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)

def main():
    m931 = load(MELT931)
    table = L.table()

    # ---- A) language_* 本地化 ----
    print("== A) language 键本地化 ==")
    cnt = 0
    for k, v in table.items():
        if k.startswith("language_") or "language" in k.lower():
            print("   ", k, "=", v[:60])
            cnt += 1
            if cnt > 25:
                break
    print("   ... 共匹配键:", sum(1 for k in table if k.startswith("language_")))

    # ---- B) 玩家语言 ----
    print("\n== B) 玩家 languages (melt931) ==")
    chars = {}
    for sec in ("living", "dead_unprunable", "dead_prunable"):
        for cid, c in (m931.get(sec) or {}).items():
            if isinstance(c, dict):
                chars.setdefault(cid, c)
    for cid in ("38725", "16836221", "16820097"):
        c = chars.get(cid) or {}
        ad = c.get("alive_data") or {}
        print("   ", cid, c.get("first_name"), "| languages:", ad.get("languages"))

    # ---- C) 王子词本地化 ----
    print("\n== C) 王子词本地化 ==")
    for k in ("prince_male_celestial_chinese", "princess_female_celestial_chinese",
              "prince_kingdom_celestial_chinese", "prince_kingdom_celestial_chinese_independent",
              "princess_kingdom_celestial_chinese"):
        print("   ", k, "=", L.loc(table, k))

    # ---- D) 路岩/杨玄翼 在 prompts.log ----
    print("\n== D) prompts.log 中 路岩/杨玄翼 ==")
    with open(PROMPTS, "r", encoding="utf-8") as fp:
        txt = fp.read()
    for name in ("路岩", "杨玄翼", "李漼", "唐皇朝", "李儇"):
        idxs = [m.start() for m in re.finditer(name, txt)]
        print("   ", name, "出现次数:", len(idxs))
        if idxs:
            i = idxs[0]
            print("      上下文:", txt[max(0, i - 120):i + 80].replace("\n", " ")[:220])
    # 唐皇朝 全部上下文
    print("\n   唐皇朝 所有出现上下文 (前5):")
    for i in [m.start() for m in re.finditer("唐皇朝", txt)][:5]:
        print("      ...", txt[max(0, i - 60):i + 60].replace("\n", " ")[:140])

    # ---- E) 家族恩怨录 正文 ----
    print("\n== E) 家族恩怨录 正文 (前 90 行) ==")
    with open(MD, "r", encoding="utf-8") as fp:
        md = fp.read()
    m = re.search(r"## 5、《家族恩怨录》\n(.*?)(?:\n## )", md, re.S)
    if m:
        for ln in m.group(1).splitlines()[:90]:
            if ln.strip():
                print("   ", ln[:110])

    # ---- F) 刺客列传 正文开头 ----
    print("\n== F) 刺客列传 正文 (前 40 行) ==")
    m = re.search(r"## 8、《刺客列传·刀下诸魂》\n(.*?)(?:\n## )", md, re.S)
    if m:
        for ln in m.group(1).splitlines()[:40]:
            if ln.strip():
                print("   ", ln[:110])

    # ---- G) 孙子 16836221 alive_data 全键 ----
    print("\n== G) 孙子 alive_data 键 ==")
    c = chars.get("16836221") or {}
    ad = c.get("alive_data") or {}
    print("   alive_data keys:", list(ad.keys()))
    print("   court_data:", c.get("court_data"))
    print("   dead_data:", c.get("dead_data"))
    print("   顶层键:", list(c.keys()))

if __name__ == "__main__":
    main()
