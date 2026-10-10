# -*- coding: utf-8 -*-
"""v121 探针（五）：在熔件里找出所有「头骨高脚杯」宝物的原始 description，
看它引用了哪个人物 id，并核对缓存里该人物的生卒与死因、与传主的关系。

只在熔件上做一次流式正则扫，不整载 272MB JSON。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

MELT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "output", "田所2", "data", "melt_972_01_01.json")
CACHE = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    ROOT, "output", "田所2", "data", "player_67183194.json")

print("melt:", MELT)
needle = '"name":"头骨高脚杯"'
hits = []
CHUNK = 1 << 24
overlap = 4096
tail = ""
pos = 0
with open(MELT, encoding="utf-8") as fp:
    while True:
        buf = fp.read(CHUNK)
        if not buf:
            break
        data = tail + buf
        for m in re.finditer(re.escape(needle), data):
            hits.append((pos - len(tail) + m.start(), data[m.start():m.start() + 1600]))
        tail = data[-overlap:]
        pos += len(buf)
print("命中「头骨高脚杯」:", len(hits))
for off, blob in hits:
    dm = re.search(r'"description":"(.*?)","type"', blob, re.S)
    print("-" * 60)
    print("  offset", off)
    print("  desc  :", repr(dm.group(1)) if dm else "?")
    refs = re.findall(r"ONCLICK:CHARACTER,(\d+)", blob)
    print("  引用人物:", refs)
    hm = re.search(r'"history":\{"entries":\[(.*)', blob, re.S)
    print("  history:", (hm.group(1)[:400] if hm else "?"))

cache = json.load(open(CACHE, encoding="utf-8"))
ch = cache["characters"]
pid = cache.get("player_id")
print("=" * 60)
print("player_id =", pid)
for _off, blob in hits:
    for ref in re.findall(r"ONCLICK:CHARACTER,(\d+)", blob):
        c = ch.get(str(ref)) or {}
        print(f"  人物 {ref}: {c.get('name_zh')} 家名={c.get('dynasty_name')}"
              f" 生={c.get('birth')} 卒={(c.get('death') or {}).get('date')}"
              f" 死因={(c.get('death') or {}).get('reason')}"
              f" 性别={'女' if c.get('female') else '男'}")
        fam = c.get("family") or {}
        print("     亲属:", {k: v for k, v in fam.items()})
