# -*- coding: utf-8 -*-
"""归因: extract_snapshot 的 109s 花在哪? 抽样计时各子步骤, 为索引方案提供依据。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cache_lib as cl

MELT = r"D:\Roman\output\菲利普3\data\melt_913_01_01.json"
CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"

melt = cl.load_melt(MELT)
cache = cl.load_cache(CACHE)
chars = cl.all_characters(melt)
db = cl._db(melt)
secrets = (melt.get("secrets") or {}).get("secrets") or {}

print(f"全角色 {len(chars)}  记忆库 {len(db)}  secrets {len(secrets)}", flush=True)
n_secret_types = {}
for s in secrets.values():
    if isinstance(s, dict):
        t = s.get("type")
        n_secret_types[t] = n_secret_types.get(t, 0) + 1
print(f"secrets 按类型: {n_secret_types}", flush=True)

# 用缓存里的角色近似目标集 (与真实 targets 同量级)
ids = [int(cid) for cid in cache["characters"] if str(cid) in chars]
print(f"缓存角色 ∩ 熔件角色: {len(ids)}", flush=True)

# 1) all_characters 单次成本
t0 = time.time()
for _ in range(20):
    cl.all_characters(melt)
print(f"all_characters 单次: {(time.time()-t0)/20*1000:.1f} ms", flush=True)

# 2) real_father_of 抽样 (直连字段 vs 秘密扫描)
sample = ids[:300]
has_direct = 0
t0 = time.time()
for cid in sample:
    rf = cl.real_father_of(melt, cid)
    if rf is not None:
        has_direct += 1
dt = time.time() - t0
print(f"real_father_of 300 次: {dt:.1f}s ({dt/300*1000:.0f} ms/次)  "
      f"其中命中直连 real_father 的 {has_direct}/300", flush=True)

# 3) 纯秘密扫描成本 (跳过 all_characters 重建, 只看 secrets 遍历)
sec_list = [s for s in secrets.values() if isinstance(s, dict)
            and s.get("type") in ("secret_unmarried_illegitimate_child",
                                  "secret_disputed_heritage")]
print(f"两类秘密数量: {len(sec_list)}", flush=True)
t0 = time.time()
hits = 0
for _ in range(20):
    for s in sec_list:
        tgt = (s.get("target") or {}).get("identity")
        if tgt is not None and int(tgt) == 38725:
            hits += 1
print(f"20 轮全量秘密扫描: {time.time()-t0:.1f}s (单轮 {(time.time()-t0)/20*1000:.0f} ms)", flush=True)

# 4) 姓名解析成本 (name_zh + house_name_zh)
t0 = time.time()
for cid in sample:
    c = chars.get(str(cid)) or {}
    cl.name_zh(c)
    h = c.get("dynasty_house")
    if h is not None:
        cl.house_name_zh(melt, h)
print(f"name_zh+house_name_zh 300 次: {time.time()-t0:.2f}s", flush=True)

# 5) memory_brief 抽样
mem_ids = [mid for c in list(chars.values())[:2000]
           for mid in cl.mem_ids_of(c) if db.get(str(mid))]
print(f"抽样记忆数: {len(mem_ids)}", flush=True)
t0 = time.time()
for mid in mem_ids[:2000]:
    cl.memory_brief(mid, db.get(str(mid)))
print(f"memory_brief 2000 次: {time.time()-t0:.2f}s", flush=True)

# 6) 外推: 若 real_father_of 全量走 (14k 目标), 各子项占比
n_targets = len(ids)
est_rf = dt / len(sample) * n_targets
print(f"\n外推 14k 目标: real_father_of ≈ {est_rf:.0f}s, "
      f"姓名解析 ≈ {(time.time()-t0)/2000*n_targets*2:.0f}s(估)", flush=True)
