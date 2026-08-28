# -*- coding: utf-8 -*-
"""v11 复测: 仅 extract_snapshot 耗时 (改前 109.3s)。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cache_lib as cl

MELT = r"D:\Roman\output\菲利普3\data\melt_913_01_01.json"
CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"

t0 = time.time()
melt = cl.load_melt(MELT)
cache = cl.load_cache(CACHE)
print(f"load: {time.time()-t0:.1f}s", flush=True)

new_deaths = []
t0 = time.time()
cl.extract_snapshot(cache, melt, "913.1.1", _new_deaths=new_deaths)
print(f"extract_snapshot: {time.time()-t0:.1f}s (改前 109.3s), new_deaths={len(new_deaths)}",
      flush=True)
print(f"characters={len(cache['characters'])} sources={len(cache['sources'])}", flush=True)
