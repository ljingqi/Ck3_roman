# -*- coding: utf-8 -*-
"""v66 性能实测：用地名取值口对 build_facts 的耗时影响（D2-b 评估用）。

用法: & tools\\tools\\py.ps1 tools\\bench_v66_names.py [家族] [玩家id] [as_of] [轮数]

口径：同一份熔件/缓存下连跑 N 轮 `build_facts`，报最短/中位耗时。熔件只载一次
（`load_melt` 的记忆化），故数字只反映**事实构建**这一侧的差异；用地名查表
（`_dyn_hist` 记忆化 + 每个头衔几条变化点）都算在里面。
"""
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = argv[0] if argv else "菲利普2"
    pid = int(argv[1]) if len(argv) > 1 else 60836
    as_of = None if len(argv) < 3 or argv[2] in ("final", "none", "-") else argv[2]
    rounds = int(argv[3]) if len(argv) > 3 else 3
    data = os.path.join(ROOT, "output", folder, "data")
    cache = cl.load_cache(os.path.join(data, f"player_{pid}.json"), fresh=True)
    melts = sorted(x for x in os.listdir(data)
                   if x.startswith("melt_") and "_idx" not in x
                   and x.endswith((".json", ".json.gz", ".json.xz")))
    print(f"载入熔件 {melts[-1]} …", flush=True)
    melt = cl.load_melt(os.path.join(data, melts[-1]))
    names = os.path.join(ROOT, "data", "names.json")
    ts = []
    for i in range(rounds):
        t0 = time.perf_counter()
        F.build_facts(cache, melt, names, as_of=as_of)
        ts.append(time.perf_counter() - t0)
        print(f"  第 {i + 1} 轮 {ts[-1]:.2f}s", flush=True)
    print(f"build_facts {folder}/{pid} as_of={as_of or 'final'}: "
          f"最短 {min(ts):.2f}s / 中位 {statistics.median(ts):.2f}s "
          f"({rounds} 轮)")
    tbl = cache.get("title_dyn_names") or {}
    print(f"  沿革表: 头衔 {len(tbl)} / 变化点 "
          f"{sum(len(v) for v in tbl.values())} / "
          f"{len(json.dumps(tbl, ensure_ascii=False, separators=(',', ':'))) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
