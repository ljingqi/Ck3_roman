"""v122 第3问取证二: 头衔 17057 是什么、金元惠(16912738) 1057 档里持有什么。

用法: & tools\py.ps1 tools\tests\v122_probe_kim2.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MELT = r"output\田所2\data\melt_1057_01_01.json"
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


def find(path, needle, before, after, limit=8):
    nb = needle.encode("utf-8")
    out = []
    with open(path, "rb") as fp:
        tail = b""
        off = 0
        while len(out) < limit:
            chunk = fp.read(1 << 23)
            if not chunk:
                break
            buf = tail + chunk
            base = off - len(tail)
            start = 0
            while len(out) < limit:
                i = buf.find(nb, start)
                if i < 0:
                    break
                out.append((base + i, buf[max(0, i - before):i + after]))
                start = i + 1
            off += len(chunk)
            tail = buf[-before:]
    return out


P("=== 头衔 '17057' 的 title 块 ===")
for o, w in find(MELT, '"17057":{', 60, 1200, limit=3):
    P(f"--- 偏移 {o}")
    P(w.decode("utf-8", "replace"))
    P()

P("=== 金元惠 的角色块 (熔件 1057) ===")
for o, w in find(MELT, '"first_name":"Won_hye"', 120, 1600, limit=3):
    P(f"--- 偏移 {o}")
    P(w.decode("utf-8", "replace"))
    P()

P("=== '16912738' 作为值出现的位置 (前 12 处) ===")
for o, w in find(MELT, '"16912738"', 150, 120, limit=12):
    P(f"--- 偏移 {o}: {w.decode('utf-8', 'replace')!r}")

open(r"logs\v122_probe_kim2.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122_probe_kim2.txt")
