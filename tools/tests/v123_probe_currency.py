"""v123 第5问取证: 从 melt_878_01_01.json 取出哈利(38950) 的 alive_data 货币/健康字段。

原始文本流式扫描 + 花括号配平, 不整载熔件 (见 .agents/skills/snapshot-testing)。
用法: tools\py.ps1 tools\tests\v123_probe_currency.py
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MELT = os.path.join(ROOT, "output", "波特", "data", "melt_878_01_01.json")
LOG = os.path.join(ROOT, "logs", "v123_probe_currency.txt")
NEEDLE = re.compile(r'"38950":\{')
text = ""
with io.open(MELT, "r", encoding="utf-8", errors="ignore") as f:
    text = f.read()
out = []
for m in NEEDLE.finditer(text):
    start = m.end() - 1
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    raw = text[start:i + 1]
    try:
        obj = json.loads(raw)
    except Exception as e:                                          # noqa: BLE001
        out.append("parse fail %s" % e)
        continue
    if "family_data" not in obj and "alive_data" not in obj:
        continue
    ad = obj.get("alive_data") or {}
    ld = obj.get("landed_data") or {}
    out.append("=== cid 38950")
    out.append("  alive_data keys: %s" % sorted(ad.keys()))
    out.append("  landed_data keys: %s" % sorted(ld.keys()))
    for k in ("health", "stress", "piety", "prestige", "influence", "merit", "herd",
              "provisions", "gold", "income", "currency", "domicile_type"):
        if k in ad:
            out.append("  alive_data[%s] = %s" % (k, json.dumps(ad[k], ensure_ascii=False)))
    for k in ("government", "herd", "provisions", "domain", "domicile_type", "tier"):
        if k in ld:
            out.append("  landed_data[%s] = %s" % (k, json.dumps(ld[k], ensure_ascii=False)))
io.open(LOG, "w", encoding="utf-8").write("\n".join(out) + "\n")
print("\n".join(out))
