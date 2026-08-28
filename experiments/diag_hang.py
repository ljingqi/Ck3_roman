# -*- coding: utf-8 -*-
"""诊断 continue 卡死: 重放 913.1.1 并入的各个步骤并计时 (只读, 不写项目数据)。

复现 17:27 那次运行的 _process_save 流程:
  melt_save(已完成, 熔件已存在) → load_melt → find_player → extract_snapshot
  → _move_melt_into(已完成) → _recover_dead_memories → save_session_cache
  → _cross_check_deaths
每步计时 + 打印系统内存余量, 定位卡点。
"""
import ctypes
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cache_lib as cl
import pipeline

MELT = r"D:\Roman\output\菲利普3\data\melt_913_01_01.json"
CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def mem():
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m


def t(label, fn):
    s = time.time()
    r = fn()
    dt = time.time() - s
    m = mem()
    print(f"[{dt:9.1f}s] {label}   (内存剩余 {m.ullAvailPhys / 2**30:.1f}/{m.ullTotalPhys / 2**30:.1f} GB)",
          flush=True)
    return r


def main():
    m = mem()
    print(f"=== 系统内存: 总计 {m.ullTotalPhys / 2**30:.1f} GB, 可用 {m.ullAvailPhys / 2**30:.1f} GB ===",
          flush=True)
    cfg = pipeline.llm.load_config()

    melt = t("load_melt(913.1.1)", lambda: cl.load_melt(MELT))
    print(f"   living={len(cl._living(melt))}  dead_unprunable={len(cl._dead_unprunable(melt))}  "
          f"dead_prunable={len(cl._dead_prunable(melt))}  db={len(cl._db(melt))}",
          flush=True)
    pid = t("find_player", lambda: cl.find_player(melt))
    print(f"   player_id={pid}  playthrough={melt.get('playthrough_id')}  date={melt.get('date')}",
          flush=True)

    cache = t("load_cache(player_38725)", lambda: cl.load_cache(CACHE))
    print(f"   last_date={cache.get('last_date')}  sources={len(cache.get('sources') or [])}  "
          f"characters={len(cache.get('characters') or {})}", flush=True)

    # --- 阶段 2: extract_snapshot (重放, 捕获 new_deaths) ---
    new_deaths = []
    ok = t("extract_snapshot(913.1.1)", lambda: cl.extract_snapshot(
        cache, melt, "913.1.1", _new_deaths=new_deaths))
    print(f"   ok={ok}  new_deaths={len(new_deaths)}", flush=True)
    print(f"   merge 后: characters={len(cache.get('characters') or {})}  "
          f"sources={len(cache.get('sources') or [])}  last_date={cache.get('last_date')}",
          flush=True)

    # --- 阶段 3: _recover_dead_memories 的候选扫描 + 分组 (不加载熔件, 先数规模) ---
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
    print(f"   待回溯角色数: {len(pending)}", flush=True)
    by_melt = {}
    for cid, mp, ddate, src, rec in pending:
        by_melt.setdefault(mp, []).append((cid, ddate, src, rec))
    print(f"   需加载的不同熔件数: {len(by_melt)}", flush=True)
    for mp, items in list(by_melt.items())[:8]:
        print(f"     - {os.path.basename(mp)} ({len(items)} 角色)", flush=True)

    # --- 阶段 4: 实际回溯 (加载每份熔件 + 恢复记忆) ---
    recovered = 0
    for mp, items in by_melt.items():
        m2 = t(f"load_melt({os.path.basename(mp)})",
               lambda mp=mp: cl.load_melt(mp))
        for cid, ddate, src, rec in items:
            n = cl.recover_dead_memories_from(m2, cache, int(cid))
            if n:
                recovered += 1
        del m2
    print(f"   回溯完成: {recovered} 角色补全记忆", flush=True)

    # --- 阶段 5: save_session_cache 的写盘开销 (dump 到临时文件, 不写项目目录) ---
    tmp_path = os.path.join(tempfile.gettempdir(), "diag_cache_dump_913.json")
    t("json.dump 缓存(indent=1)", lambda: (
        open(tmp_path, "w", encoding="utf-8").write(
            json.dumps(cache, ensure_ascii=False, indent=1)) or None))
    print(f"   缓存落盘大小: {os.path.getsize(tmp_path) / 2**20:.1f} MB", flush=True)
    try:
        os.remove(tmp_path)
    except OSError:
        pass

    # --- 阶段 6: _cross_check_deaths 的遍历规模 ---
    dead_unpr = melt.get("dead_unprunable") or {}
    t("遍历 dead_unprunable", lambda: sum(
        1 for _cid, c in dead_unpr.items() if isinstance(c, dict)))

    print("=== 诊断完成 ===", flush=True)


if __name__ == "__main__":
    main()
