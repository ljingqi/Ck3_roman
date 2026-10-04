# -*- coding: utf-8 -*-
"""v98 阅读页核对：index.html 是否收录三篇新稿（按内容串与篇目标签）。"""
import re

p = r"D:\Roman\output\洪氏2\index.html"
t = open(p, encoding="utf-8").read()
print("index.html %d 字节" % len(t))
for pat in ("欢乐者洪思忠", "欢乐者尼各老", "截至963年", "截至973年", "截至983年",
            "纪事·枢机团与教宗选举", "洪思忠(917)", "尼各老(917)"):
    print("  %-14s %d" % (pat, t.count(pat)))
pairs = re.findall(r'"label": "(第\d个十年传记)", "meta": "(至\d+\.01\.01)"', t)
print("十年篇条目: %s" % pairs)
