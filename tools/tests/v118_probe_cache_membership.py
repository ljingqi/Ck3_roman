"""v118 probe: which volumes' caches carry the early generations of the played chain?

For every player cache of 洪氏2, report whether the four ancestors the last volume is missing
(38957 洪秀全 / 44503 洪天贵福 / 67172818 尼各老 / 16879059 洪审礼) are present, with name/birth
and whether they even carry a death record. One cache is parsed at a time and released, so the
process never holds the whole campaign.

Usage: & tools\\py.ps1 tools\\tests\\v118_probe_cache_membership.py
"""
import gc
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "output" / "洪氏2" / "data"
ANCIENTS = [38957, 44503, 67172818, 16879059]


def main():
    files = sorted(DATA.glob("player_*.json"),
                   key=lambda p: int(re.search(r"player_(\d+)", p.name).group(1)))
    for p in files:
        cache = json.loads(p.read_text(encoding="utf-8"))
        chars = cache.get("characters") or {}
        hits = []
        for cid in ANCIENTS:
            rec = chars.get(str(cid))
            if rec is None:
                hits.append(f"{cid}:—")
            else:
                hits.append(f"{cid}:{rec.get('name_zh')!r}/"
                            f"{(rec.get('death') or {}).get('date') or 'alive'}")
        print(f"{p.name:<26} n={len(chars):>6} "
              f"chain={len(cache.get('played_legacy') or []):>2} | " + "  ".join(hits))
        del cache, chars
        gc.collect()


if __name__ == "__main__":
    main()
