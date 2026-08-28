# -*- coding: utf-8 -*-
"""离线验证修复效果 (不调 LLM): 时间线规模/去重/选角/提示词体积。"""
import json
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cache_lib as cl
import facts as F
import biography as bio

CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
MELT = r"D:\Roman\output\菲利普3\data\melt_912_01_01.json"
NAMES = r"D:\Roman\data\names.json"

cache = json.load(open(CACHE, encoding="utf-8"))
melt = cl.load_melt(MELT)
facts = F.build_facts(cache, melt, NAMES)

tl = facts["timeline"]
print("== 新时间线 ==")
print("条数:", len(tl), "| 字符:", sum(len(e["text"]) for e in tl))
by_year = {}
for e in tl:
    y = str(e["date"] or "").split(".")[0]
    by_year[y] = by_year.get(y, 0) + 1
print("首年:", min(by_year), "末年:", max(by_year), "| 882-892 条数:",
      sum(v for k, v in by_year.items() if 882 <= int(k) <= 892),
      "| 893-912 条数:", sum(v for k, v in by_year.items() if 893 <= int(k) <= 912))

# 死亡去重抽查: 同一死者应只出现一次死亡表述
import re
death_names = {}
for e in tl:
    t = e["text"]
    m = re.search(r"殁于\d+年\d+月\d+日", t)
    if m:
        nm = t.split("殁于")[0].rstrip("，, ")
        death_names.setdefault(nm, []).append(t)
dups = {k: v for k, v in death_names.items() if len(v) > 1}
print("重复死亡表述人数:", len(dups))
for k, v in list(dups.items())[:5]:
    print("  DUP:", k, "->", len(v), "条")

# 选角
articles = bio.build_articles(facts, cache, {})
print("\n== 选角 ==")
friend = next((a["subject"] for a in articles if a["key"] == "friend"), None)
enemy = next((a["subject"] for a in articles if a["key"] == "enemy"), None)
print("好友:", friend)
print("仇人:", enemy)

# 提示词体积: 总纲 + 各文章首段 (不调 LLM)
cfg = {"data_dir": r"D:\Roman\data", "max_tokens": 12800,
       "bio_sections": ["lead", "mid", "tail"]}
intro_msgs = bio.build_intro_messages(facts, cfg, articles)
intro_chars = sum(len(m["content"]) for m in intro_msgs)
print("\n== 提示词体积 ==")
print("总纲提示词字符:", intro_chars, "≈ tokens:", intro_chars // 2)
for a in articles:
    msgs = bio.build_lead_messages(a, facts, cache, "（总纲略）", cfg)
    c = sum(len(m["content"]) for m in msgs)
    print(f"  首段《{a['title']}》: {c} 字符 ≈ {c // 2} tokens")
