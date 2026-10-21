# -*- coding: utf-8 -*-
"""v121 探针（九）：一次熔件加载，把四问的「改动前事实面」全部取证。

用法：& tools\\py.ps1 tools\\tests\\v121_probe_head_all.py
产物：logs/v121/v121_probe_head_all.txt
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import biography as bio   # noqa: E402
import cache_lib as cl    # noqa: E402
import facts as F         # noqa: E402

FOLDER, PID, MELT = "田所2", 72914, "melt_972_01_01.json"
data = os.path.join(ROOT, "output", FOLDER, "data")
cache = json.load(open(os.path.join(data, f"player_{PID}.json"), encoding="utf-8"))
names = os.path.join(data, "names.json")
if not os.path.exists(names):
    names = os.path.join(ROOT, "data", "names.json")
campaign = {}
for fn in os.listdir(data):
    m = re.match(r"player_(\d+)\.json$", fn)
    if not m:
        continue
    try:
        c = json.load(open(os.path.join(data, fn), encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        continue
    if c.get("playthrough_id") == cache.get("playthrough_id"):
        campaign[int(m.group(1))] = c
print(f"载入熔件 {MELT} …", flush=True)
melt = cl.load_melt(os.path.join(data, MELT))
facts = F.build_facts(cache, melt, names, as_of=None, decade=None,
                      campaign=campaign or None)
f = facts["_facts"]
chars = cache["characters"]


def find(name):
    return [int(k) for k, v in chars.items()
            if (v.get("name") or v.get("name_full")) == name]


print("\n" + "=" * 78)
print("【问4】世系里的「前X」：这些人到底还持不持有那个头衔")
print("=" * 78)
for nm in ("田所健六", "田所健五", "田所亮三", "田所健二", "田所亮四"):
    for cid in find(nm):
        rec = chars[str(cid)]
        dd = (rec.get("death") or {}).get("date")
        anchor = f._anchor_date(cid, None)
        print(f"\n-- {nm} (id={cid})  卒={dd}  anchor={anchor}")
        print(f"   person_label(full) = {f.person_label(cid, None, 'full')!r}")
        print(f"   official_title     = {f.official_title(cid, None)!r}")
        print(f"   _primary_title_at  = {f._primary_title_at(cid, as_of=anchor)}")
        print(f"   _current_title_tid = {f._current_title_tid(cid, anchor)}")
        ft = f._former_high_title(cid, anchor,
                                  exclude_tid=f._current_title_tid(cid, anchor))
        print(f"   _former_high_title = {ft}")
        for tid, ivs in (f._hold_intervals(cid, anchor) or {}).items():
            key = (f._lt.get(str(tid)) or {}).get("key") or "?"
            for (g, l, lt) in ivs:
                print(f"      tid={tid} key={key} eff_rank={f._eff_rank(tid)} "
                      f"gain={g} loss={l} type={lt}"
                      f"{'   ← 本条即 former 选中的' if tid == ft else ''}")

print("\n" + "=" * 78)
print("【问3】宝物：头骨/遗骨类材质的实际下发内容")
print("=" * 78)
for blk in (f.family_artifacts() or []):
    if any(w in blk for w in ("头骨", "遗骨", "之骨", "剩的骨头", "材质")):
        print("-" * 60)
        print(blk)

print("\n" + "=" * 78)
print("【问1】传主档案行（出生句与地名行）")
print("=" * 78)
for ln in bio._profile_lines(facts, None):
    print("  " + ln)

print("\n" + "=" * 78)
print("【问2】959.3 的 joined_allys_war 行数与样本")
print("=" * 78)
rows = [e for e in facts["timeline"] if e.get("type") == "joined_allys_war"]
print(f"timeline 总数={len(facts['timeline'])}  joined_allys_war={len(rows)}")
by = {}
for e in rows:
    by.setdefault(str(e.get("date") or "")[:6], []).append(e)
for k in sorted(by):
    if len(by[k]) >= 2:
        print(f"  {k}* → {len(by[k])} 行")
for e in by.get("959.3.", [])[:6]:
    print("    " + e["date"] + " " + e["text"])
