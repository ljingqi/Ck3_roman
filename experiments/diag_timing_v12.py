# -*- coding: utf-8 -*-
"""v12 稳态计时: 归档已建好后, 回溯 46 个角色 × 13 份旧熔件只需读边车索引。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cache_lib as cl
import pipeline

MELT = r"D:\Roman\output\菲利普3\data\melt_913_01_01.json"
CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"

melt = cl.load_melt(MELT)
cache = cl.load_cache(CACHE)
cfg = pipeline.llm.load_config()
new_deaths = []
cl.extract_snapshot(cache, melt, "913.1.1", _new_deaths=new_deaths)
sources = cache.get("sources") or []
pending = []
for cid, rec in (cache.get("characters") or {}).items():
    d = rec.get("death") or {}
    ddate = d.get("date")
    if not ddate or rec.get("memories"):
        continue
    if int(cid) not in new_deaths:
        continue
    before = [s for s in sources if cl.date_key(s) < cl.date_key(ddate)]
    if not before:
        continue
    mp = pipeline.melt_path_for_cache(cfg, cache, before[-1])
    if not os.path.isfile(mp):
        continue
    pending.append((cid, mp, ddate, before[-1], rec))
by_melt = {}
for cid, mp, ddate, src, rec in pending:
    by_melt.setdefault(mp, []).append((cid, mp, ddate, src, rec))
print(f"待回溯 {len(pending)} 角色, {len(by_melt)} 份熔件", flush=True)

missing = [mp for mp in by_melt if not os.path.isfile(cl.melt_index_path(mp))]
if missing:
    print(f"缺归档 {len(missing)} 份, 先补建: {[os.path.basename(m) for m in missing]}", flush=True)
    for mp in missing:
        m = cl.load_melt(mp)
        cl.save_melt_index(mp, m)

t0 = time.time()
recovered = 0
for mp, items in by_melt.items():
    idx = cl.load_melt_index(mp)
    for cid, _mp, ddate, src, rec in items:
        n = cl.recover_dead_memories_from_index(idx, cache, int(cid))
        if n:
            recovered += 1
dt = time.time() - t0
print(f"纯归档回溯: {dt:.1f}s, 补全 {recovered} 角色 (改前全量路径 ~87s)", flush=True)
