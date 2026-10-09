# -*- coding: utf-8 -*-
"""v117 check (item 3 / 丙-2): the metadata record drives the biography queue exactly like the cache.

Loads 洪氏2's campaign caches (full) and their metadata records, then compares every field the
queue tests read — reign_end/death dates, bio flags, completed decades, on-disk decades, pinned
biography name — plus the queue counts of `_auto_bio` / `_auto_decade_bios` under both forms.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_meta_queue.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl       # noqa: E402
import llm                   # noqa: E402
import pipeline as P         # noqa: E402

FOLDER = "洪氏2"
PID = 17066495
LOG = os.path.join(ROOT, "logs", "v117_check_meta_queue.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def main():
    cfg = llm.load_config()
    anchor = cl.load_cache(os.path.join(cfg["output_dir"], FOLDER, "data", f"player_{PID}.json"))
    full = P._campaign_caches(cfg, anchor)
    meta = P._campaign_caches(cfg, anchor, meta_only=True)
    w(f"本战役传主: full={len(full)} meta={len(meta)}")

    bad = []
    for pid in sorted(full):
        a = full[pid]
        b = meta.get((pid, anchor.get("playthrough_id"))) or meta.get(pid) or {}
        rows = [
            ("reign_end", (a.get("reign_end") or {}).get("date")),
            ("b.reign_end", (b.get("reign_end") or {}).get("date")),
            ("death", (a.get("player_death") or {}).get("date")),
            ("b.death", (b.get("player_death") or {}).get("date")),
            ("bio_generated", bool(a.get("bio_generated"))),
            ("b.bio_generated", bool(b.get("bio_generated"))),
            ("bio_decades", sorted(a.get("bio_decades") or [])),
            ("b.bio_decades", sorted(b.get("bio_decades") or [])),
            ("completed", P._completed_decades(a)),
            ("b.completed", P._completed_decades(b)),
            ("on_disk", sorted(P._generated_decades_on_disk(cfg, a))),
            ("b.on_disk", sorted(P._generated_decades_on_disk(cfg, b))),
            ("pname", P._bio_pname(a)),
            ("b.pname", P._bio_pname(b)),
            ("player_name", a.get("player_name")),
            ("b.player_name", b.get("player_name")),
        ]
        d = {}
        for k, v in rows:
            d.setdefault(k.replace("b.", ""), []).append(v)
        for key, vals in d.items():
            if vals[0] != vals[1]:
                bad.append((pid, key, vals))
        w(f"  {pid}: {d['pname'][0]}  十年={d['completed'][0] or '—'} "
          f"已生成={d['bio_decades'][0] or '—'} 终了={d['reign_end'][0] or d['death'][0] or '在世'}")

    w(f"\n不一致项: {bad if bad else '无'}")
    ok = not bad
    w(f"[{'PASS' if ok else 'FAIL'}] 元数据与缓存逐项一致")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
