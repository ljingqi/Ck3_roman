# -*- coding: utf-8 -*-
"""定点重建某一战役文件夹的玩家缓存 (v38 开发用)。

背景: pipeline.rebuild-cache 会遍历**全部** output/* 文件夹 (11 个战役、150+ 份
熔件, 数小时)。本脚本只重建指定文件夹, 一次加载一份熔件, 把其中**所有**玩家
(前代与当代) 各并入各自缓存, 再对各缓存做死者记忆回溯。

用法:
    & tools\\tools\\py.ps1 tools\\rebuild_folder_v38.py 周氏5
"""
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cache_lib as cl          # noqa: E402
import llm                      # noqa: E402
import pipeline as pl           # noqa: E402

PAT = re.compile(r"^melt_(\d+_\d{2}_\d{2})\.json(?:\.gz|\.xz)?$")


def main():
    cfg = llm.load_config()
    folder = sys.argv[1] if len(sys.argv) > 1 else ""
    if not folder:
        print("用法: rebuild_folder_v38.py <家族文件夹>")
        return 1
    data_dir = os.path.join(cfg.get("output_dir", ""), folder, "data")
    if not os.path.isdir(data_dir):
        print(f"无此文件夹: {data_dir}")
        return 1
    cands = []
    for fn in os.listdir(data_dir):
        m = PAT.match(fn)
        if m:
            date = ".".join(str(int(x)) for x in m.group(1).split("_"))
            cands.append((cl.date_key(date), date, os.path.join(data_dir, fn)))
    cands.sort()
    print(f"文件夹 {folder}: {len(cands)} 份熔件")
    caches = {}     # pid -> cache
    order = []      # 首次出现顺序
    t0 = time.time()
    for i, (_k, date, path) in enumerate(cands, 1):
        t1 = time.time()
        melt = cl.load_melt(path)
        pid = cl.find_player(melt)
        pts = {str(v) for v in caches}
        _ = pts
        # 本档玩家
        pids = []
        if pid is not None:
            pids.append(pid)
        # 本档出现过的其他玩家 (前代): 缓存里已有的 pid 也并入本档
        for cid in list(caches):
            if cid not in pids:
                pids.append(cid)
        for p in pids:
            cache = caches.get(p)
            if cache is None:
                prev_path = os.path.join(data_dir, f"player_{p}.json")
                prev = cl.load_cache(prev_path) if os.path.isfile(prev_path) else {}
                cache = cl.new_cache()
                for k in ("player_death", "bio_generated", "bio_decades",
                          "playthrough_id", "output_folder"):
                    if prev.get(k):
                        cache[k] = prev[k]
                caches[p] = cache
                order.append(p)
            ok = cl.extract_snapshot(cache, melt, date)
            if ok is False:
                continue
            cache["output_folder"] = folder
        print(f"  [{i}/{len(cands)}] {date} 玩家={pid} "
              f"({time.time() - t1:.1f}s)")
        del melt
    # 死者记忆回溯 + 落盘
    for p in order:
        cache = caches[p]
        n = pl._recover_dead_memories(cfg, cache)
        out = os.path.join(data_dir, f"player_{p}.json")
        cl.save_cache(cache, out)
        print(f"  player {p}: {len(cache.get('characters') or {})} 角色, "
              f"回溯 {n} 人, last={cache.get('last_date')} → {out}")
    print(f"完成, 用时 {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
