"""v122 第1问取证三: 记忆库里 1119 年关于 178021 的记忆类型 —— 死亡类还是失地类。

记忆是游戏自己写的 (on_action 建), 谁在 1119.7 前后对 178021 留了 death 记忆,
就说明游戏认为他死了; 只有 title_lost / abdication 类记忆则说明他只是失地。
用法: & tools\py.ps1 tools\tests\v122_probe_mem.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cache_lib as cl  # noqa: E402

MP = r"output\田所2\data\melt_1120_01_01.json"
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


idx = cl.load_melt_index(MP)
if not idx:
    P("无记忆边车")
    sys.exit(1)
db = idx.get("db") or {}
P(f"记忆条数: {len(db)}")

TARGET = 178021
hits = []
for mid, e in db.items():
    pd = e.get("participants")
    parts = []
    if isinstance(pd, dict):
        for k, v in pd.items():
            if isinstance(v, list):
                parts += [x for x in v if isinstance(x, int)]
            elif isinstance(v, int):
                parts.append(v)
    elif isinstance(pd, list):
        parts = [x for x in pd if isinstance(x, int)]
    if TARGET in parts:
        hits.append((str(e.get("creation_date") or ""), mid, e.get("type"), pd,
                     e.get("vars")))
P(f"涉及 {TARGET} 的记忆: {len(hits)} 条")
hits.sort()
for cr, mid, ty, pd, vars_ in hits:
    P(f"  {cr}  {ty}  id={mid}  participants={pd}")
    P(f"      vars={vars_}")
P()
P("样例: 8 条含 death 字样的记忆")
n = 0
for mid, e in db.items():
    if "death" in str(e.get("type") or ""):
        P(f"  {e.get('creation_date')}  {e.get('type')}  {e.get('participants')}")
        n += 1
        if n >= 8:
            break
P()
P("1119 年 (1119.6~1119.9) 创建的全部记忆类型分布:")
from collections import Counter  # noqa: E402
c = Counter()
for mid, e in db.items():
    cr = str(e.get("creation_date") or "")
    if cr.startswith("1119."):
        c[e.get("type")] += 1
for k, v in c.most_common(40):
    P(f"  {k}: {v}")

open(r"logs\v122_probe_mem.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122_probe_mem.txt")
