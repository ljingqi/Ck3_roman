# -*- coding: utf-8 -*-
"""v12 端到端: 调用真实 pipeline._recover_dead_memories (归档优先路径)。
只读加载, 不落盘缓存; 日志会写入 journal.log (与真实运行一致)。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cache_lib as cl
import pipeline

MELT = r"D:\Roman\output\菲利普3\data\melt_913_01_01.json"
CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"

cfg = pipeline.llm.load_config()
melt = cl.load_melt(MELT)
cache = cl.load_cache(CACHE)
new_deaths = []
cl.extract_snapshot(cache, melt, "913.1.1", _new_deaths=new_deaths)
print(f"extract 完成, new_deaths={len(new_deaths)}, characters={len(cache['characters'])}",
      flush=True)

t0 = time.time()
n = pipeline._recover_dead_memories(cfg, cache, new_deaths)
print(f"_recover_dead_memories (归档优先): {time.time()-t0:.1f}s, 补全 {n} 角色", flush=True)
