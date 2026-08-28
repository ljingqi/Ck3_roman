# -*- coding: utf-8 -*-
"""v11 优化验证: real_father_of 预索引后 (1) 结果与旧实现逐目标一致 (2) 耗时对比。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cache_lib as cl

MELT = r"D:\Roman\output\菲利普3\data\melt_913_01_01.json"
CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"


def real_father_of_OLD(melt, cid):
    """旧实现原样拷贝 (验证基准)。"""
    cid = int(cid)
    chars = cl.all_characters(melt)
    c = chars.get(str(cid)) or {}
    fd = c.get("family_data") or {}
    rf = fd.get("real_father")
    if rf is not None:
        return int(rf)
    sec = (melt.get("secrets") or {}).get("secrets") or {}
    for s in sec.values():
        if not isinstance(s, dict):
            continue
        if s.get("type") not in ("secret_unmarried_illegitimate_child",
                                 "secret_disputed_heritage"):
            continue
        tgt = (s.get("target") or {}).get("identity")
        if tgt is None or int(tgt) != cid:
            continue
        owner = s.get("owner")
        cands = [int(x) for x in (s.get("participants") or []) if isinstance(x, int)]
        cands = [x for x in cands if x != cid]
        if owner is not None and isinstance(owner, int):
            cands = [x for x in cands if x != owner]
        for cand in cands:
            cc = chars.get(str(cand)) or {}
            if not cc.get("female"):
                return cand
        if cands:
            return cands[0]
    return None


melt = cl.load_melt(MELT)
cache = cl.load_cache(CACHE)
chars = cl.all_characters(melt)
sec_idx = cl._secret_father_candidates(melt)

ids = [int(cid) for cid in cache["characters"] if str(cid) in chars]
print(f"目标角色: {len(ids)}", flush=True)

# ---- 正确性: 新旧逐目标对比 ----
t0 = time.time()
mismatch = 0
for cid in ids:
    old = real_father_of_OLD(melt, cid)
    new = cl.real_father_of(melt, cid, chars, sec_idx)
    if old != new:
        mismatch += 1
        if mismatch <= 5:
            print(f"  不一致 cid={cid}: old={old} new={new}", flush=True)
print(f"正确性: {len(ids) - mismatch}/{len(ids)} 一致, 用时 {time.time()-t0:.1f}s", flush=True)

# ---- 性能: 新实现全量 (含预建索引) ----
t0 = time.time()
sec_idx2 = cl._secret_father_candidates(melt)
n = 0
for cid in ids:
    if cl.real_father_of(melt, cid, chars, sec_idx2) is not None:
        n += 1
dt_new = time.time() - t0
print(f"新实现全量 {len(ids)} 目标: {dt_new:.1f}s (含索引预建), 命中 {n}", flush=True)

# ---- 性能: 旧实现抽样外推 ----
sample = ids[:300]
t0 = time.time()
for cid in sample:
    real_father_of_OLD(melt, cid)
dt_old_sample = time.time() - t0
print(f"旧实现外推 {len(ids)} 目标: ≈{dt_old_sample / len(sample) * len(ids):.0f}s", flush=True)
