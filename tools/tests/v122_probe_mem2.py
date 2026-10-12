"""v122 第1问取证四: 递归抽取 participants 里的全部角色 id, 找 1119.7 前后「谁死了」的记忆。

若 178021 真的死了, 他的亲属/友人/配偶会在死日留下 *d/ *died 类记忆, 且死亡的当事人是 178021。
用法: & tools\py.ps1 tools\tests\v122_probe_mem2.py
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cache_lib as cl  # noqa: E402

MP = r"output\田所2\data\melt_1120_01_01.json"
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


def deep_ints(v, out):
    if isinstance(v, bool):
        return
    if isinstance(v, int):
        out.append(v)
    elif isinstance(v, list):
        for x in v:
            deep_ints(x, out)
    elif isinstance(v, dict):
        for x in v.values():
            deep_ints(x, out)


idx = cl.load_melt_index(MP)
db = idx.get("db") or {}
TARGET = 178021

P("A. 全部涉及 178021 的记忆 (按类归并计数):")
c = Counter()
for mid, e in db.items():
    ids = []
    deep_ints(e.get("participants"), ids)
    if TARGET in ids:
        c[e.get("type")] += 1
for k, v in c.most_common():
    P(f"  {k}: {v}")

P()
P("B. 1119.7.10~1119.7.20 之间, 所有 *died* / death 类记忆:")
n = 0
for mid, e in db.items():
    cr = str(e.get("creation_date") or "")
    ty = str(e.get("type") or "")
    if cr.startswith("1119.7.") and ("died" in ty or "death" in ty):
        P(f"  {cr}  {ty}  participants={e.get('participants')}")
        n += 1
P(f"  共 {n} 条")

P()
P("C. 1119.7.15 当天全部记忆类型分布:")
c2 = Counter()
for mid, e in db.items():
    if str(e.get("creation_date") or "") == "1119.7.15":
        c2[e.get("type")] += 1
for k, v in c2.most_common(30):
    P(f"  {k}: {v}")

P()
P("D. 1119.7.15 且 participants 含 178021 的每条记忆全文:")
for mid, e in db.items():
    if str(e.get("creation_date") or "") != "1119.7.15":
        continue
    ids = []
    deep_ints(e.get("participants"), ids)
    if TARGET in ids:
        P(f"  type={e.get('type')} participants={e.get('participants')} vars={e.get('vars')}")

P()
P("E. 178021 名下 1119 年 (全部 1119.*) 的记忆:")
for mid, e in db.items():
    cr = str(e.get("creation_date") or "")
    if not cr.startswith("1119."):
        continue
    ids = []
    deep_ints(e.get("participants"), ids)
    if TARGET in ids:
        P(f"  {cr}  {e.get('type')}  participants={e.get('participants')} vars={e.get('vars')}")

open(r"logs\v122_probe_mem2.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122_probe_mem2.txt")
