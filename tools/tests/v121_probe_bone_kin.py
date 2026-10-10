# -*- coding: utf-8 -*-
"""v121 探针（七）：骨骼宝物材质里点名的那个人，程序端到底能不能给出「亲属关系 + 生卒 + 死因」。

对 72914（田所健二）的缓存，验 33581196（田所列子，头骨主人）：
  · 亲属词：走 `_kin_word` / `blood_kin_word_for` 用的同一套 kin_key / kin_text
  · 死因：走 style.DEATH_REASON_ZH（facts 的死亡句出处）
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import json
import facts as F  # noqa: E402
import style  # noqa: E402

cache = json.load(open(os.path.join(ROOT, "output", "田所2", "data",
                                    "player_72914.json"), encoding="utf-8"))
pid, vid = 72914, 33581196
chars = cache["characters"]
print("kin_key  =", F.kin_key(cache, pid, vid))
print("kin_text =", F.kin_text(F.kin_key(cache, pid, vid)))
print("short    =", F.kin_word_short(F.kin_key(cache, pid, vid)))
v = chars[str(vid)]
print("生=", v.get("birth"), "卒=", (v.get("death") or {}).get("date"),
      " 死因=", (v.get("death") or {}).get("reason"),
      "->", style.DEATH_REASON_ZH.get((v.get("death") or {}).get("reason")))
print("性别女 =", v.get("female"))
# 父辈关系：亮一(49313) vs 亮四(16801324) 同为 38990 之子
for a, b in ((49313, 16801324), (38990, 49313)):
    print(f"  kin_key({a},{b}) =", F.kin_key(cache, a, b), F.kin_text(F.kin_key(cache, a, b)))
