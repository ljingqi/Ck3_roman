# -*- coding: utf-8 -*-
"""v121 探针（二）：直接对 logs/prompts.log 里的原样行跑聚合正则，逐条报匹配结果。"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402

pat = F._AGG_SPEC["joined_allys_war"]["pat"]
print("pat =", repr(pat))

LOG = os.path.join(ROOT, "logs", "prompts.log")
lines = open(LOG, encoding="utf-8").read().splitlines()

samples = [
    "宇井家族女士诗人藤原朝子随剥皮者田所健二出战，对抗关白藤原兼长，此役为罢免战争。",
    "伊予家族女士伊予稳子随剥皮者田所健二出战，对抗关白藤原兼长，此役为罢免战争。",
    "河内国司源进随关白藤原兼长出战，对抗剥皮者田所健二，此役为罢免战争。",
]
for s in samples:
    m = re.match(pat, s)
    print(repr(s), "->", "OK" if m else "MISS", m.groups() if m else "")

# 从日志里抽出所有「随…出战，对抗…」片段，逐个测
found = 0
miss = []
for ln in lines:
    for piece in re.split(r"[；。]", ln):
        piece = piece.strip()
        m = re.match(r"^(?:\d+年(?:\d+月(?:\d+日)?)?，)?(.*)$", piece)
        body = m.group(1) if m else piece
        if "出战，对抗" not in body:
            continue
        found += 1
        if not re.match(pat, body):
            miss.append(body)
print("含「出战，对抗」片段 =", found, " 未匹配 =", len(miss))
seen = []
for b in miss:
    if b not in seen:
        seen.append(b)
for b in seen[:20]:
    print("  MISS:", repr(b))
print("唯一未匹配形态 =", len(seen))

# 逐字符查可疑空白
for b in seen[:6]:
    sp = [(i, hex(ord(c))) for i, c in enumerate(b) if c.isspace()]
    print("  空白:", b[:24], sp)
