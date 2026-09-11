# -*- coding: utf-8 -*-
"""只重建**一个**战役文件夹的缓存（tools/rebuild_folder.py）

用法：
    & D:\\Roman\\tools\\py.ps1 tools\\rebuild_folder.py 马克龙 [玩家id]

为什么要有它：`pipeline.py rebuild-cache` 遍历 `output/` 下**全部**战役文件夹的熔件
（实测上百份，每份 1–3 分钟，数小时）；迭代时只需要重建当前在看的那一个战役。

口径与 `step_rebuild_cache` 一致：
  · **空缓存重建**（不是把旧快照重放上去）——重放会让 `trait_history` 的差分拿
    末档 traits 当基线，凭空生成一整轮「获得/消失」区间；
  · 保留 `player_death` / `bio_generated` / `bio_decades` / `playthrough_id`
    / `output_folder`（生成进度与战役身份不能丢）；
  · 结束时跑一次 `_recover_dead_memories`（死者记忆回溯）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl          # noqa: E402
import llm                      # noqa: E402
import pipeline as pipe         # noqa: E402

_MELT_RE = None


def _melts_in(data_dir):
    import re
    global _MELT_RE
    if _MELT_RE is None:
        _MELT_RE = re.compile(r"melt_(\d+_\d{2}_\d{2})(?:_p\d+)?\.json$")
    out = []
    for fn in os.listdir(data_dir):
        m = _MELT_RE.match(fn)
        if m:
            out.append((os.path.join(data_dir, fn),
                        ".".join(str(int(x)) for x in m.group(1).split("_"))))
    out.sort(key=lambda x: cl.date_key(x[1]))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    folder = sys.argv[1]
    only_pid = int(sys.argv[2]) if len(sys.argv) > 2 else None
    cfg = llm.load_config()
    data_dir = os.path.join(cfg.get("output_dir", ""), folder, "data")
    if not os.path.isdir(data_dir):
        print(f"找不到战役数据目录: {data_dir}")
        return 2
    melds = _melts_in(data_dir)
    if not melds:
        print(f"没有熔件: {data_dir}")
        return 2
    print(f"{folder}: {len(melds)} 份熔件 ({melds[0][1]} → {melds[-1][1]})", flush=True)

    first = cl.load_melt(melds[0][0])
    pid = only_pid or cl.find_player(first)
    if pid is None:
        print("熔件里没有玩家角色")
        return 2
    del first
    cache_path = os.path.join(data_dir, f"player_{pid}.json")
    prev = {}
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as fp:
                prev = json.load(fp) or {}
        except Exception:
            prev = {}
    cache = cl.new_cache()
    for k in ("player_death", "bio_generated", "bio_decades", "playthrough_id"):
        if prev.get(k):
            cache[k] = prev[k]
    cache["output_folder"] = prev.get("output_folder") or folder

    for path, date in melds:
        melt = cl.load_melt(path)
        cl.extract_snapshot(cache, melt, date)
        print(f"  {date}: 角色 {len(cache['characters'])}, "
              f"牵制 {len(cache.get('hooks') or {})}, "
              f"隐事 {len(cache.get('secrets_history') or {})}", flush=True)
        del melt
    pipe._recover_dead_memories(cfg, cache)
    cl.save_cache(cache, cache_path)
    print(f"已写入: {cache_path} "
          f"(角色 {len(cache['characters'])}, 牵制 {len(cache.get('hooks') or {})})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
