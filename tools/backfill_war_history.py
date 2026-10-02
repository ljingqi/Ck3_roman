# -*- coding: utf-8 -*-
"""回填缓存 `war_history`（v95 问题1）

用法：
    & tools\\py.ps1 tools\\backfill_war_history.py <家族文件夹> [玩家id] [--check]

为什么需要它：真 CB 只在 `wars.active_wars[].casus_belli.type`，而**战争一结束就从
存档移除**（本档对立教宗那战 946.2.24 结束，947 档起无踪）。本项目 1.20 起新并入的档
会由 `cache_lib._latch_war_history` 自动落盘；但**已有的缓存**是 v95 之前建的，里面
没有这一键 ⇒ 用本脚本把战役文件夹里**现存**的熔件逐档补回来。

为什么不用 rebuild_folder：那是「空缓存重建」，会把 trait_history 等差分基线一并重算
（历史上每次都要 snapdiff 逐项对照）。本脚本只加 `war_history` 一键、幂等，且**不整载
熔件** —— 只取 `wars` 段（`cache_lib.load_melt_section`，实测 0.3 s/档，全档 50 余份
数秒完成），缓存其余部分逐字节不动。

--check：只报告将要写入的行数与涉及本玩家的战争，不写盘。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl          # noqa: E402
import llm                      # noqa: E402

_MELT_RE = re.compile(r"melt_(\d+_\d{2}_\d{2})(?:_p\d+)?\.json(?:\.gz|\.xz)?$")


def _melts_in(data_dir):
    out = []
    for fn in os.listdir(data_dir):
        m = _MELT_RE.match(fn)
        if m:
            out.append((os.path.join(data_dir, fn),
                        ".".join(str(int(x)) for x in m.group(1).split("_"))))
    out.sort(key=lambda x: cl.date_key(x[1]))
    return out


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    if not argv:
        print(__doc__)
        return 2
    folder = argv[0]
    only_pid = int(argv[1]) if len(argv) > 1 else None
    cfg = llm.load_config()
    data_dir = os.path.join(cfg.get("output_dir", ""), folder, "data")
    if not os.path.isdir(data_dir):
        print(f"找不到战役数据目录: {data_dir}")
        return 2
    melts = _melts_in(data_dir)
    if not melts:
        print(f"没有熔件: {data_dir}")
        return 2
    print(f"{folder}: {len(melts)} 份熔件 ({melts[0][1]} → {melts[-1][1]})", flush=True)

    if only_pid is not None:
        pids = [only_pid]
    else:
        pids = []
        for fn in os.listdir(data_dir):
            if fn.startswith("player_") and fn.endswith(".json"):
                try:
                    pids.append(int(fn[len("player_"):-len(".json")]))
                except ValueError:
                    continue
        pids.sort()
    if not pids:
        print("没有 player_*.json")
        return 2

    for pid in pids:
        path = os.path.join(data_dir, f"player_{pid}.json")
        if not os.path.isfile(path):
            print(f"跳过 player_{pid}.json (不存在)")
            continue
        with open(path, encoding="utf-8") as fp:
            cache = json.load(fp)
        before = len(cache.get("war_history") or [])
        added = 0
        for mp, date in melts:
            wars = cl.load_melt_section(mp, "wars")
            if not isinstance(wars, dict):
                continue
            added += cl._latch_war_history(cache, wars, date, cache.get("player_id"))
        rows = cache.get("war_history") or []
        print(f"player_{pid}: 原有 {before} 行, 新闩 {added} 行, 共 {len(rows)} 行",
              flush=True)
        for row in rows:
            print("    %s cb=%s atk=%s dfd=%s parts=%s/%s"
                  % (row.get("start_date"), row.get("cb"), row.get("attacker"),
                     row.get("defender"), row.get("atk_parts"), row.get("dfd_parts")),
                  flush=True)
        if check:
            print("    --check: 未写盘")
            continue
        cl.save_cache(cache, path)
        print(f"    已写入: {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
