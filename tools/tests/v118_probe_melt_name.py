"""v118 probe: is the 11th 刀下亡魂 (cid 321250, "米娜") present in each melt, and with what name?

Segment-level reads only (`cache_lib.load_melt_section`), no full melt parse and no re-melt.
Usage: & tools\\py.ps1 tools\\tests\\v118_probe_melt_name.py [cid] [years...]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import cache_lib as cl  # noqa: E402

DATA = ROOT / "output" / "洪氏2" / "data"


def main():
    args = [a for a in sys.argv[1:]]
    cid = args[0] if args else "321250"
    years = args[1:] or ["1282", "1283", "1284", "1285"]
    for y in years:
        p = DATA / f"melt_{y}_01_01.json"
        if not p.is_file():
            print(f"{y}: no file {p.name}")
            continue
        t0 = time.time()
        living = cl.load_melt_section(str(p), "living") or {}
        t1 = time.time()
        dead = cl.load_melt_section(str(p), "dead_unprunable") or {}
        t2 = time.time()
        chars = cl.load_melt_section(str(p), "characters") or {}
        dp = (chars.get("dead_prunable") or {}) if isinstance(chars, dict) else {}
        rec = living.get(cid) or dead.get(cid) or dp.get(cid)
        where = ("living" if cid in living else
                 "dead_unprunable" if cid in dead else
                 "dead_prunable" if cid in dp else "-")
        name = cl.name_zh(rec) if isinstance(rec, dict) else None
        dd = (rec or {}).get("dead_data") or {}
        print(f"{y}: where={where} name_zh={name!r} "
              f"dead_date={dd.get('date')!r} killer={dd.get('killer')!r} "
              f"living={len(living)} dead_unprunable={len(dead)} dead_prunable={len(dp)} "
              f"[living {t1-t0:.1f}s, dead {t2-t1:.1f}s]")


if __name__ == "__main__":
    main()
