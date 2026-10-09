"""v118 check · fix A: the tail-year victim gets a cache record created.

`pipeline._backfill_tail_deaths` normally parses the whole death-after melt; here the two sections it
reads are taken segment-wise (`cl.load_melt_section`) and the cache write is stubbed out, so the
effect can be checked in ~20 s without touching any file on disk. The cache in memory is a copy.

Usage: & tools\\py.ps1 tools\\tests\\v118_check_fix_a.py
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import cache_lib as cl           # noqa: E402
import llm                       # noqa: E402
import pipeline as PL            # noqa: E402

DATA = ROOT / "output" / "洪氏2" / "data"
PID = 17066495
VICTIM = 321250                  # 米娜, killed 1283.8.28, absent from the volume's cache


def main():
    cfg = llm.load_config()
    cache = json.loads((DATA / f"player_{PID}.json").read_text(encoding="utf-8"))
    tail = PL.tail_melt_candidate(cfg, cache)
    print(f"tail melt = {tail}")
    real_load = cl.load_melt

    def section_load(path):
        return {"dead_unprunable": cl.load_melt_section(path, "dead_unprunable") or {},
                "characters": cl.load_melt_section(path, "characters") or {}}

    cl.load_melt = section_load
    saved = []
    PL.save_cache_now = lambda path, c: saved.append(path)
    try:
        n, melt = PL._backfill_tail_deaths(cfg, cache)
    finally:
        cl.load_melt = real_load
    print(f"backfilled={n} melt={'yes' if melt else 'no'} save_stubbed={len(saved)} call(s)")
    rec = (cache.get("characters") or {}).get(str(VICTIM)) or {}
    print(f"victim {VICTIM} record keys = {sorted(rec)}")
    for k in ("name_zh", "name_full", "birth", "female", "culture", "faith", "death"):
        print(f"  {k}: {rec.get(k)!r}")
    ok = rec.get("name_zh") == "米娜" and (rec.get("death") or {}).get("date") == "1283.8.28" \
        and (rec.get("death") or {}).get("killer") == PID
    print("FIX-A CHECK:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
