# -*- coding: utf-8 -*-
"""v12 记忆归档验证: 边车索引 (1) 构建规模/耗时 (2) 回溯结果与全量熔件完全一致
(3) 归档回溯与全量回溯耗时对比。"""
import copy
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cache_lib as cl

MELT = r"D:\Roman\output\菲利普3\data\melt_913_01_01.json"
CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
CIDS = [16795720, 16796268, 16796274, 16799596, 16802930, 16805081, 16809721,
        16815851, 16820840, 16822689, 16836196, 33598754]  # 之前日志里的死角色样本

# ---- 1) 构建规模/耗时 ----
melt = cl.load_melt(MELT)
t0 = time.time()
idx = cl.build_melt_index(melt)
dt = time.time() - t0
print(f"build_melt_index: {dt:.1f}s", flush=True)
print(f"  归档 chars={len(idx['chars'])} db={len(idx['db'])}", flush=True)
tmp = os.path.join(os.environ.get("TEMP", "."), "diag_idx_test.json")
with open(tmp, "w", encoding="utf-8") as fp:
    import json
    json.dump(idx, fp, ensure_ascii=False)
print(f"  归档 JSON 大小: {os.path.getsize(tmp) / 2**20:.1f} MB (全量 {os.path.getsize(MELT) / 2**20:.0f} MB)",
      flush=True)
os.remove(tmp)

# ---- 2) 一致性: 全量回溯 vs 归档回溯 (同一份缓存深拷贝) ----
cache_full = cl.load_cache(CACHE)
cache_idx = cl.load_cache(CACHE)
t0 = time.time()
n_full = sum(cl.recover_dead_memories_from(melt, cache_full, cid) for cid in CIDS)
dt_full = time.time() - t0
t0 = time.time()
n_idx = sum(cl.recover_dead_memories_from_index(idx, cache_idx, cid) for cid in CIDS)
dt_idx = time.time() - t0
print(f"\n全量回溯 {len(CIDS)} 角色: {n_full} 条, {dt_full:.1f}s", flush=True)
print(f"归档回溯 {len(CIDS)} 角色: {n_idx} 条, {dt_idx:.1f}s", flush=True)
same = True
for cid in CIDS:
    a = cache_full["characters"].get(str(cid), {}).get("memories") or []
    b = cache_idx["characters"].get(str(cid), {}).get("memories") or []
    if a != b:
        same = False
        print(f"  不一致 cid={cid}: 全量 {len(a)} 条 vs 归档 {len(b)} 条", flush=True)
print(f"一致性: {'完全一致' if same else '存在差异!'}", flush=True)

# ---- 3) 归档读取耗时 (模拟日常回溯加载) ----
idx_path = cl.melt_index_path(MELT)
cl.save_melt_index(MELT, melt)
t0 = time.time()
idx2 = cl.load_melt_index(MELT)
print(f"\nload_melt_index: {time.time()-t0:.2f}s (全量 load_melt ~8s)", flush=True)
print(f"边车路径: {idx_path}", flush=True)
