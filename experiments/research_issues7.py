# -*- coding: utf-8 -*-
"""研究第七波: 刺客块精确大小, 语言名称映射, 击杀者记忆统计。"""
import json
import sys
import re
from collections import Counter

sys.path.insert(0, r"D:\Roman")
import localization as L

MELT931 = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"
PROMPTS = r"D:\Roman\logs\prompts.log"
CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"

def load(path):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)

def main():
    # ---- A) 刺客块大小 (最后一次出现, 直到下一个空行块) ----
    print("== A) 刺客列传 prompt 块 ==")
    with open(PROMPTS, "r", encoding="utf-8") as fp:
        txt = fp.read()
    idxs = [m.start() for m in re.finditer(r"刀下诸魂", txt)]
    print("   出现次数:", len(idxs))
    for i in idxs:
        # 向后找该块的结尾: 下一个 "===" 或 "\n  " 前
        seg = txt[i:i + 400000]
        end = seg.find("\n\n  ")
        if end < 0:
            end = seg.find("=====")
        blk = seg[:end if end > 0 else 300000]
        n = len(re.findall(r"死者：", blk))
        print("   位置 %d: 块字符数 %d, 死者数 %d" % (i, len(blk), n))

    # ---- B) 击杀者: 168 人的可写性统计 ----
    print("\n== B) 168 击杀者素材统计 ==")
    cache = load(CACHE)
    chars = cache.get("characters") or {}
    pid = cache.get("player_id")
    kills = set((chars.get(str(pid)) or {}).get("kills") or [])
    pd = cache.get("player_death") or {}
    kills |= set(pd.get("kills") or [])
    fam = (chars.get(str(pid)) or {}).get("family") or {}
    fam_ids = set()
    for k in ("primary_spouse", "spouse", "former_spouses", "child",
              "concubine", "former_concubines"):
        for x in fam.get(k) or []:
            fam_ids.add(int(x))
    enemy_mem = {"became_rivals", "became_grudge", "became_nemesis"}
    enemy_ids = set()
    for cid, rec in chars.items():
        for m in rec.get("memories") or []:
            if m.get("type") in enemy_mem and pid in (m.get("participants") or {}).values():
                enemy_ids.add(int(cid))
    friend_mem = {"became_friends", "became_soulmates", "became_blood_brother"}
    friend_ids = set()
    for cid, rec in chars.items():
        for m in rec.get("memories") or []:
            if m.get("type") in friend_mem and pid in (m.get("participants") or {}).values():
                friend_ids.add(int(cid))
    n_mem = 0
    n_house = 0
    n_fam = 0
    n_rel = 0
    n_zero = 0
    for cid in kills:
        rec = chars.get(str(cid)) or {}
        mems = len(rec.get("memories") or [])
        if mems > 0:
            n_mem += 1
        if rec.get("house_name"):
            n_house += 1
        if cid in fam_ids:
            n_fam += 1
        if cid in enemy_ids or cid in friend_ids or cid in fam_ids:
            n_rel += 1
        if mems == 0 and not rec.get("house_name"):
            n_zero += 1
    print("   总击杀:", len(kills))
    print("   有记忆:", n_mem, "| 有家族:", n_house, "| 家人:", n_fam,
          "| 家人/友/仇:", n_rel, "| 无记忆且无家族(纯路人):", n_zero)
    print("   去 lowborn(无家族)后:", len(kills) - (len(kills) - n_house))
    print("   去 无记忆且无家族 后:", len(kills) - n_zero)
    print("   去 无记忆(无论家族)后:", len(kills) - (len(kills) - n_mem))

    # ---- C) 语言: melt931 全部出现过的 language_* ----
    print("\n== C) melt931 出现过的 language_* 种类 ==")
    m931 = load(MELT931)
    chars931 = {}
    for sec in ("living", "dead_unprunable", "dead_prunable"):
        for cid, c in (m931.get(sec) or {}).items():
            if isinstance(c, dict):
                chars931.setdefault(cid, c)
    langs = Counter()
    for c, in ():
        pass
    for cid, c in chars931.items():
        for lg in (c.get("alive_data") or {}).get("languages") or []:
            langs[lg] += 1
    print("   种类数:", len(langs))
    table = L.table()
    for lg, n in langs.most_common(30):
        v = L.loc(table, lg)
        # 尝试 culture_template 对应
        print("   ", lg, "x", n, "| loc:", repr(v)[:40])

    # ---- D) culture_template 中文 ----
    print("\n== D) culture_template 中文 (语言名候选) ==")
    for tpl in ("norse", "japonic", "arabic", "sayhadic", "anglic", "han",
                "balhae", "greek", "frankish", "italian", "saxon"):
        print("   ", tpl, "=", L.loc(table, tpl) or L.loc(table, tpl.capitalize()) or "(无)")

if __name__ == "__main__":
    main()
