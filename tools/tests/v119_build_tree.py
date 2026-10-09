# -*- coding: utf-8 -*-
"""v119 rebuild: write data/genealogy.json from the newest save, and time the clan-wide tree build.

The tree sidecar is normally written by a biography run (`biography._write_genealogy_tree`). This
probe runs the same facts build the 封档总评 uses (newest cache + latest melt, tail backfilled) and
writes the sidecar plus the reading page, so a tree-script change can be checked without an LLM call.
Nothing under output/ is deleted; the only file it replaces is the tree sidecar and index.html, both
program artifacts.

Usage:  python tools/tests/v119_build_tree.py [家族文件夹]     (default 洪氏2)
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import biography as bio        # noqa: E402
import cache_lib as cl         # noqa: E402
import facts as F              # noqa: E402
import htmlview as H           # noqa: E402
import llm                     # noqa: E402
import pipeline as P           # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "洪氏2"


def main():
    cfg = llm.load_config()
    out_dir = cfg["output_dir"]
    folder = os.path.join(out_dir, FOLDER)
    cands = [c for c in P.epilogue_candidates(cfg) if c["folder"] == FOLDER]
    if not cands:
        print(f"{FOLDER} 没有终传，无从确定基准人物")
        return 1
    row = cands[0]
    path = P.find_cache_path(cfg, row["pid"], None)
    print(f"基准人物 {row['pid']} · 缓存 {os.path.basename(path or '')}", flush=True)
    t0 = time.time()
    cache = cl.load_cache(path)
    melt = P.load_latest_melt(cfg, cache)
    if melt is None:
        print("无可用 melt")
        return 1
    if P.tail_state_applies(cache):
        _n, tail = P._backfill_tail_deaths(cfg, cache)
        P._merge_tail_title_flags(melt, tail)
    t1 = time.time()
    print(f"缓存 + 熔件 {t1 - t0:.1f}s（last_date {cache.get('last_date')}）", flush=True)

    facts = F.build_facts(cache, melt, bio._names_path(cfg, cache), cfg=cfg,
                          campaign=P._campaign_caches(cfg, cache))
    t2 = time.time()
    print(f"facts 构建 {t2 - t1:.1f}s", flush=True)
    tree = facts.get("genealogy_tree") or {}
    nodes = tree.get("nodes") or []
    clan = [n for n in nodes if n.get("clan")]
    print(f"家谱：珠 {len(nodes)}（其中族外新增 {len(clan)}）· 传主 {len(tree.get('chain') or [])} 位"
          f" · 配偶珠 {tree.get('spouse_n')} · 房 {len(tree.get('houses') or [])} 个"
          f" · 谱外 {tree.get('clan_orphans')}")
    print(f"表记：{tree.get('summary')}")
    for h in (tree.get("houses") or [])[:12]:
        print(f"    {h['label']:<14}{h['n']:>5} 人{'  ← 传主房' if h.get('chain') else ''}")
    t3 = time.time()
    bio._write_genealogy_tree(facts, os.path.join(folder, "_tree_probe.md"))
    print(f"落盘家谱数据 {time.time() - t3:.1f}s → data/genealogy.json"
          f"（{os.path.getsize(os.path.join(folder, 'data', 'genealogy.json')) / 1024:.0f} KB）",
          flush=True)
    if "--page" in sys.argv:
        t4 = time.time()
        H.rebuild_folder(out_dir, FOLDER)
        print(f"阅读页重建 {time.time() - t4:.1f}s", flush=True)
    print(f"合计 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
