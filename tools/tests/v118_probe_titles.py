"""v118 probe: what titles did the 世系 ancestors hold? Reads the production cache once.

Prints the played chain, then the realm/title history rows that record cids 38957 (洪秀全),
44503 (洪天贵福), 67172818 (尼各老), 16879059 (洪审礼).
Usage: & tools\\py.ps1 tools\\tests\\v118_probe_titles.py [cache.json] [cid...]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "output" / "洪氏2" / "data" / "player_17066495.json"
WANT = [38957, 44503, 67172818, 16879059, 16878235]


def main():
    cache_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CACHE
    want = [int(x) for x in sys.argv[2:]] or WANT
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    print("== played_legacy ==")
    for e in cache.get("played_legacy") or []:
        print(" ", json.dumps(e, ensure_ascii=False))
    print("\n== cache top-level keys ==")
    print(" ", [k for k in cache if k not in ("characters",)])
    rh = cache.get("realm_history") or []
    print(f"\n== realm_history rows: {len(rh)} ==")
    if rh:
        print(" first row keys:", list(rh[0]))
        print(" first row:", json.dumps(rh[0], ensure_ascii=False)[:600])
    # find every title whose holder list or tenure touches a wanted cid
    for row in rh:
        holders = row.get("holders") or {}
        for tid, h in holders.items():
            if isinstance(h, list):
                cids = {int(x) for x in h if isinstance(x, int)}
            elif isinstance(h, int):
                cids = {h}
            else:
                cids = set()
            if cids & set(want):
                print(f"\n-- title {tid} name={row.get('name') or row.get('title_name')!r}")
                print("   row:", json.dumps({k: v for k, v in row.items() if k != 'holders'},
                                            ensure_ascii=False)[:400])
                for c in sorted(cids & set(want)):
                    print(f"   holder {c}")


if __name__ == "__main__":
    main()
