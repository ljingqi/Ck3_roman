"""v122 第3问取证: 金元惠在存档里是谁 —— 拿字节上下文定位角色块与它的头衔字段。

用法: & tools\py.ps1 tools\tests\v122_probe_kim.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cache_lib as cl  # noqa: E402

OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


def scan(path, needle, before=400, after=900, limit=20):
    """Yield (offset, window) for each occurrence of needle bytes (chunked, boundary-safe)."""
    nb = needle.encode("utf-8")
    size = os.path.getsize(path)
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
    return out, size


CACHE = r"output\田所2\data\player_67220811.json"
P(f"== 玩家缓存 {CACHE} ==")
hits, size = scan(CACHE, "金元惠")
P(f"文件 {size} 字节, 命中 {len(hits)} 处")
for o, w in hits[:8]:
    P(f"--- 偏移 {o}")
    P(w.decode("utf-8", "replace"))
    P()

# 若缓存里出现 id, 再到熔件里找该角色块
ids = set()
for o, w in hits:
    for m in re.finditer(rb'"(\d{3,})":\{"first_name":"' + "金元惠".encode("utf-8") + rb'"', w):
        ids.add(int(m.group(1)))
P(f"从缓存窗口里取到的角色 id: {sorted(ids)}")

if not ids:
    MELT = r"output\田所2\data\melt_1057_01_01.json"
    P(f"== 熔件 {MELT} 里找 金元惠 的角色块 ==")
    hits2, size2 = scan(MELT, '"first_name":"' + "金元惠" + '"', before=120, after=1500, limit=6)
    P(f"文件 {size2} 字节, 命中 {len(hits2)} 处")
    for o, w in hits2:
        P(f"--- 偏移 {o}")
        P(w.decode("utf-8", "replace"))
        P()

open(r"logs\v122\v122_probe_kim.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122/v122_probe_kim.txt")
