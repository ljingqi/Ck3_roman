"""v122 取证: 从 prompts.log 里摘出含关键字的请求块 (块 = '===== 时间 =====' 之间), 只印命中行上下 25 行。

用法: & tools\py.ps1 tools\tests\v122_probe_prompts.py 阉割 掌玺大臣 金元惠 御前会议
"""
import io
import os
import sys

LOG = r"logs\prompts.log"
KEYS = sys.argv[1:] or ["阉割"]
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


text = io.open(LOG, encoding="utf-8").read()
blocks = []
cur = []
for ln in text.split("\n"):
    if ln.startswith("===== ") and cur:
        blocks.append(cur)
        cur = []
    cur.append(ln)
if cur:
    blocks.append(cur)
P(f"请求块总数: {len(blocks)}; 关键字: {KEYS}")

for kw in KEYS:
    P()
    P("=" * 20 + f" 关键字 {kw} " + "=" * 20)
    n = 0
    for b in blocks:
        hits = [i for i, ln in enumerate(b) if kw in ln]
        if not hits:
            continue
        n += 1
        ts = b[0].strip()
        P(f"--- {ts}  (命中 {len(hits)} 处, 块内 {len(b)} 行)")
        shown = set()
        for i in hits[:6]:
            lo, hi = max(0, i - 12), min(len(b), i + 8)
            if any(x in shown for x in range(lo, hi)):
                continue
            shown.update(range(lo, hi))
            for j in range(lo, hi):
                mark = ">>" if j == i else "  "
                P(f"{mark}{j:5d}| {b[j][:200]}")
            P("      ...")
        if n >= 6:
            break
    P(f"[{kw}] 命中请求块 {n} 个 (最多印 6 个)")

open(r"logs\v122_probe_prompts.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122_probe_prompts.txt")
