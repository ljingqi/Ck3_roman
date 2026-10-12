"""v122 第1问取证五: 直接在 1120 熔件字节流里找 178021 的每一处出现, 看它落在哪个顶层段。

若游戏把他写成死人, 字节流里一定另有 dead_data / dead 段的那一份; 只有 living 一份
则「没死」是存档事实, 不是程序的推断错误。
用法: & tools\py.ps1 tools\tests\v122_probe_bytes.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MP = r"output\田所2\data\melt_1120_01_01.json"
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


pat = re.compile(rb'"178021"\s*:')
# 顶层段起点: 顶格 (行首无缩进) 的 "key": —— rakaly 输出为一键一行
sec_pat = re.compile(rb'\n"([A-Za-z_0-9]+)"\s*:')

hits = []
offset = 0
size = os.path.getsize(MP)
with open(MP, "rb") as fp:
    tail = b""
    while True:
        chunk = fp.read(1 << 23)
        if not chunk:
            break
        buf = tail + chunk
        base = offset - len(tail)
        for m in pat.finditer(buf):
            hits.append((base + m.start(), buf[max(0, m.start() - 120):m.start() + 40]))
        # 记录段起点位置
        for m in sec_pat.finditer(buf):
            hits.append(("SEC", base + m.start(), m.group(1).decode("utf-8", "replace")))
        offset += len(chunk)
        tail = buf[-200:]

P(f"熔件 {MP} 大小 {size}")
secs = [(o, n) for h in hits if h and h[0] == "SEC" for o, n in [(h[1], h[2])]]
secs.sort()
P(f"顶层段起点 {len(secs)} 个: " + ", ".join(f"{n}@{o}" for o, n in secs[:60]))

cid_hits = [(o, ctx) for h in hits if h and h[0] != "SEC" for o, ctx in [(h[0], h[1])]]
P()
P(f'"178021": 出现 {len(cid_hits)} 处')
for o, ctx in cid_hits:
    owner = ""
    for so, sn in secs:
        if so < o:
            owner = f"{sn}@{so}"
        else:
            break
    P(f"  偏移 {o}  所属顶层段: {owner}")
    P(f"    前文: {ctx.decode('utf-8', 'replace')!r}")

P()
P("对照: 一个确定在 dead_unprunable 的人 (28242) 与一个确定在 living 的人 (218169054):")
for want in (b'"28242"', b'"218169054"'):
    first = []
    with open(MP, "rb") as fp:
        tail = b""
        off = 0
        while len(first) < 3:
            chunk = fp.read(1 << 23)
            if not chunk:
                break
            buf = tail + chunk
            base = off - len(tail)
            for m in re.finditer(want + rb'\s*:', buf):
                first.append((base + m.start(), buf[max(0, m.start() - 100):m.start() + 30]))
            off += len(chunk)
            tail = buf[-200:]
    for o, ctx in first:
        owner = ""
        for so, sn in secs:
            if so < o:
                owner = f"{sn}@{so}"
            else:
                break
        P(f"  {want.decode()} 偏移 {o} 段={owner} 前文={ctx.decode('utf-8','replace')!r}")

open(r"logs\v122_probe_bytes.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122_probe_bytes.txt")
