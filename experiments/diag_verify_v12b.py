# -*- coding: utf-8 -*-
"""v12 归档验证 (真实场景): 复现 913.1.1 合并的 46 个待回溯角色 × 13 份旧熔件,
全量熔件回溯 vs 归档回溯结果逐角色一致, 并统计耗时对比。
副作用: 为这 13 份熔件持久化归档边车 (正是 index-melts 要做的)。"""
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

# 1) 复现 extract_snapshot 得到 new_deaths, 再算 pending (与 _recover_dead_memories 同逻辑)
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
print(f"待回溯: {len(pending)} 角色", flush=True)
by_melt = {}
for cid, mp, ddate, src, rec in pending:
    by_melt.setdefault(mp, []).append((cid, ddate, src, rec))
print(f"熔件组: {len(by_melt)}", flush=True)

# 2) 两份独立缓存分别走全量/归档路径
cache_full = cl.load_cache(CACHE)
cache_idx = cl.load_cache(CACHE)
t_full = 0.0
t_idx = 0.0
mismatch = 0
for mp, items in by_melt.items():
    # 全量路径
    t0 = time.time()
    m = cl.load_melt(mp)
    chars = cl.all_characters(m)
    for cid, ddate, src, rec in items:
        cl.recover_dead_memories_from(m, cache_full, int(cid), chars=chars)
    t_full += time.time() - t0
    # 归档路径: 构建 + 持久化 + 读取 + 回溯
    t0 = time.time()
    idx_path = cl.melt_index_path(mp)
    if not os.path.isfile(idx_path):
        cl.save_melt_index(mp, m)
    idx = cl.load_melt_index(mp)
    for cid, ddate, src, rec in items:
        cl.recover_dead_memories_from_index(idx, cache_idx, int(cid))
    t_idx += time.time() - t0

# 3) 逐角色对比缓存记忆
for cid, mp, ddate, src, rec in pending:
    a = cache_full["characters"].get(str(cid), {}).get("memories") or []
    b = cache_idx["characters"].get(str(cid), {}).get("memories") or []
    if a != b:
        mismatch += 1
        print(f"  不一致 cid={cid}: 全量 {len(a)} 条 vs 归档 {len(b)} 条", flush=True)
print(f"\n一致性: {len(pending) - mismatch}/{len(pending)} 角色完全一致", flush=True)
print(f"全量回溯总耗时: {t_full:.0f}s (13 份熔件 json.load)", flush=True)
print(f"归档回溯总耗时: {t_idx:.0f}s (含首建, 后续只读 ~0.5s/份)", flush=True)
