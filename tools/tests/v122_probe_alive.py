"""v122 第1问取证二: 1120 档 living 桶是否可靠 + 178021 全字段。

问三件事:
  A. living 桶里有没有人带 dead_data / death_date (即「在 living 里但已死」的形态);
  B. 178021 在 1120 档的完整记录 (去掉 dna);
  C. 对照: 一个确实已死的人 (dead_unprunable 抽样) 的记录长相。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cache_lib as cl  # noqa: E402

MP = r"output\田所2\data\melt_1120_01_01.json"
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


living = cl.load_melt_section(MP, "living") or {}
dead_un = cl.load_melt_section(MP, "dead_unprunable") or {}

n_dd = 0
sample = []
n_date = 0
for cid, rec in living.items():
    if not isinstance(rec, dict):
        continue
    if rec.get("dead_data"):
        n_dd += 1
        if len(sample) < 5:
            sample.append((cid, rec.get("dead_data")))
    if rec.get("death_date"):
        n_date += 1
P(f"A. living={len(living)}: 带 dead_data 的 {n_dd} 个, 带 death_date 的 {n_date} 个")
for cid, dd in sample:
    P(f"   样例 {cid}: {dd}")
# 字段频次, 看 living 记录里哪些键普遍存在
freq = {}
for rec in living.values():
    if isinstance(rec, dict):
        for k in rec:
            freq[k] = freq.get(k, 0) + 1
P("   living 记录键频次 (前 40): " + json.dumps(
    sorted(freq.items(), key=lambda kv: -kv[1])[:40], ensure_ascii=False))

P()
P("B. 178021 @1120 完整记录 (去 dna):")
rec = living.get("178021") or {}
if isinstance(rec, list):
    P(f"   !! 形状为 list, 长度 {len(rec)}")
    rec = rec[0]
    P("   首块: " + json.dumps({k: v for k, v in rec.items() if k != "dna"},
                               ensure_ascii=False)[:6000])
    for i, p in enumerate(living.get("178021")[1:], 1):
        P(f"   第{i+1}块: " + json.dumps({k: v for k, v in p.items() if k != "dna"},
                                        ensure_ascii=False)[:6000])
else:
    P(json.dumps({k: v for k, v in rec.items() if k != "dna"}, ensure_ascii=False))

P()
P("C. 1108 年 (更早档已判死) 的 178021 对照 + dead_unprunable 抽样:")
MP2 = r"output\田所2\data\melt_1119_01_01.json"
living19 = cl.load_melt_section(MP2, "living") or {}
r19 = living19.get("178021") or {}
if isinstance(r19, list):
    r19 = r19[0]
P("   1119 档 living[178021] 键: " + json.dumps(sorted(r19.keys()), ensure_ascii=False))
P("   dead_unprunable 抽样 3 例的键:")
for i, (cid, r) in enumerate(dead_un.get if False else list(dead_un.items())[:0]):
    pass
shown = 0
for cid, r in dead_un.items():
    if isinstance(r, dict) and r.get("dead_data"):
        P(f"   {cid}: 键={json.dumps(sorted(r.keys()), ensure_ascii=False)}")
        P(f"      dead_data={json.dumps(r.get('dead_data'), ensure_ascii=False)[:400]}")
        shown += 1
        if shown >= 3:
            break

open(r"logs\v122_probe_alive.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122_probe_alive.txt")
