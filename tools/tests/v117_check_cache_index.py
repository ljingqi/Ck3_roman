# -*- coding: utf-8 -*-
"""v117 check (item 3 / 丙-2): the cache metadata index.

Runs the index against a throwaway campaign directory with two fake caches, so no real save data is
touched. Asserts: metadata comes from the index (no cache parse), a rewritten cache invalidates its
entry and refreshes it, a corrupt index heals itself, the campaign filter is applied, and the full
mode still returns the parsed caches.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_cache_index.py
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl       # noqa: E402
import pipeline as P         # noqa: E402

LOG = os.path.join(ROOT, "logs", "v117_check_cache_index.txt")
TMP = os.path.join(ROOT, "logs", "_v117_idx")
DATA = os.path.join(TMP, "洪氏2", "data")
buf = []
loads = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def fake_cache(pid, pt, last, folder, death=False):
    return {
        "player_id": pid,
        "playthrough_id": pt,
        "output_folder": folder,
        "last_date": last,
        "player_name": f"玩家{pid}",
        "sources": [last],
        "characters": {str(pid): {"birth": "900.1.1", "name_zh": f"名{pid}"}},
        "player_death": {"date": last} if death else None,
    }


def write(pid, obj):
    with open(os.path.join(DATA, f"player_{pid}.json"), "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False)


def main():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(DATA)
    write(1, fake_cache(1, "pt-a", "1000.1.1", "洪氏"))
    write(2, fake_cache(2, "pt-b", "1100.1.1", "教宗尼各老", death=True))

    real_load = cl.load_cache

    def spy(path, fresh=False):
        loads.append(path)
        return real_load(path, fresh=fresh)

    cl.load_cache = spy
    cfg = {"output_dir": TMP, "cache_dir": ""}
    try:
        # [A] cold: no index yet -> both caches parsed once, index written
        loads.clear()
        a = P.all_caches(cfg, meta_only=True)
        idx_path = P.cache_index_path(DATA)
        w(f"[A] 冷启 meta_only: 条目 {len(a)}, 解析 {len(loads)} 次, 索引存在 "
          f"{os.path.isfile(idx_path)}")
        ok_a = len(a) == 2 and len(loads) == 2 and os.path.isfile(idx_path)

        # [B] warm: entries come from the index, no parse at all
        loads.clear()
        b = P.all_caches(cfg, meta_only=True)
        w(f"[B] 热读 meta_only: 条目 {len(b)}, 解析 {len(loads)} 次, "
          f"字段 {sorted((b[(1, 'pt-a')][1]).keys())[:5]}…")
        ok_b = len(b) == 2 and not loads and b[(1, "pt-a")][1]["output_folder"] == "洪氏"

        # [C] campaign filter: only the wanted campaign is returned (and none is parsed)
        loads.clear()
        c = P.all_caches(cfg, meta_only=True, playthrough_id="pt-b")
        w(f"[C] 战役过滤 pt-b: 条目 {list(c)}, 解析 {len(loads)} 次")
        ok_c = list(c) == [(2, "pt-b")] and not loads

        # [D] the full mode still returns parsed caches
        loads.clear()
        d = P.all_caches(cfg)
        cache2 = d[(2, "pt-b")][1]
        w(f"[D] 全量模式: 条目 {len(d)}, 解析 {len(loads)} 次, "
          f"player_2 是 dict={isinstance(cache2, dict)}, has_player_death="
          f"{cache2.get('player_death') is not None}")
        ok_d = len(d) == 2 and isinstance(cache2, dict) and cache2.get("player_id") == 2

        # [E] a rewritten cache invalidates its own entry only, then refreshes the index
        write(1, fake_cache(1, "pt-a", "1200.1.1", "洪氏2"))
        loads.clear()
        e = P.all_caches(cfg, meta_only=True)
        w(f"[E] 缓存改写后: 解析 {len(loads)} 次, player_1 的 last_date="
          f"{e[(1, 'pt-a')][1]['last_date']}")
        ok_e = len(loads) == 1 and e[(1, "pt-a")][1]["last_date"] == "1200.1.1"

        # [F] a corrupt index heals itself
        with open(idx_path, "w", encoding="utf-8") as fp:
            fp.write("{ not json")
        loads.clear()
        f = P.all_caches(cfg, meta_only=True)
        w(f"[F] 索引损坏后: 条目 {len(f)}, 解析 {len(loads)} 次, 索引已重写 "
          f"{os.path.isfile(idx_path)}")
        ok_f = len(f) == 2 and len(loads) == 2

        # [G] a stale stamp (size changed) forces a re-parse of that entry only
        p1 = os.path.join(DATA, "player_1.json")
        with open(p1, "a", encoding="utf-8") as fp:
            fp.write(" ")
        loads.clear()
        g = P.all_caches(cfg, meta_only=True)
        w(f"[G] 仅尺寸变化的档案: 解析 {len(loads)} 次 ({[os.path.basename(x) for x in loads]})")
        ok_g = len(loads) == 1 and os.path.basename(loads[0]) == "player_1.json" and len(g) == 2

        # [H] an index written by another schema version is ignored and rebuilt, so a field
        # added to cache_meta_fields can never be silently missing
        with open(idx_path, "w", encoding="utf-8") as fp:
            fp.write('{"version": 999, "files": {"player_1.json": {"size": 0, "mtime": 0}}}')
        loads.clear()
        h = P.all_caches(cfg, meta_only=True)
        idx_now = json.load(open(idx_path, encoding="utf-8"))
        w(f"[H] 版本不符的索引: 解析 {len(loads)} 次, 重写版本 {idx_now.get('version')}")
        ok_h = len(h) == 2 and len(loads) == 2 and idx_now.get("version") == P._CACHE_INDEX_VERSION
    finally:
        cl.load_cache = real_load
        shutil.rmtree(TMP, ignore_errors=True)

    w("")
    for name, ok in (("[A] 冷启自建索引", ok_a),
                     ("[B] 热读零解析", ok_b),
                     ("[C] 战役过滤", ok_c),
                     ("[D] 全量模式不变", ok_d),
                     ("[E] 改写后仅该条重解析", ok_e),
                     ("[F] 索引损坏自愈", ok_f),
                     ("[G] 尺寸变化失效", ok_g),
                     ("[H] 索引版本不符则重建", ok_h)):
        w(f"  {'PASS' if ok else 'FAIL'} {name}")
    ok = all((ok_a, ok_b, ok_c, ok_d, ok_e, ok_f, ok_g, ok_h))
    w(f"\n[{'PASS' if ok else 'FAIL'}] v117 丙-2 cache index check")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
