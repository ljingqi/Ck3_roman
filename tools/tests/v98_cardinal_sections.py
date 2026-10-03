# -*- coding: utf-8 -*-
"""v98 成稿核对 2：抽三篇新稿的「纪事·枢机团与教宗选举」小节全文。

输出 logs/v98_cardinal_sections.txt
"""
import os
import re

ROOT = r"D:\Roman"
F = os.path.join(ROOT, "output", "洪氏2")
OUT = os.path.join(ROOT, "logs", "v98_cardinal_sections.txt")
FILES = ["洪思忠(917)_传记_第1个十年_963_01_01.md",
         "洪思忠(917)_传记_第2个十年_973_01_01.md",
         "尼各老(917)_传记_第3个十年_983_01_01.md",
         "_v97_before/洪思忠(917)_传记_第1个十年_963_01_01.md"]
LINES = []


def P(s=""):
    LINES.append(str(s))


for fn in FILES:
    p = os.path.join(F, fn)
    if not os.path.isfile(p):
        P("(缺) %s" % fn)
        continue
    text = open(p, encoding="utf-8").read()
    P("=" * 90)
    P("### %s" % fn)
    # 小节：从「纪事·枢机团与教宗选举」到下一个 ### 或 ##
    m = re.search(r"(###[^\n]*枢机团与教宗选举[^\n]*\n)(.*?)(?=\n#{2,3} )", text, re.S)
    if not m:
        P("  (未见该小节)")
        continue
    P(m.group(1).strip())
    for para in [x.strip() for x in m.group(2).split("\n") if x.strip()]:
        P("  " + para)
    P()

open(OUT, "w", encoding="utf-8").write("\n".join(LINES) + "\n")
print("写出 %s（%d 行）" % (OUT, len(LINES)))
