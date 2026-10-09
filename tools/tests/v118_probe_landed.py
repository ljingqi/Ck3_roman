"""v118 probe: title tenures of the 世系 ancestors, straight from the melt's landed_titles section.

Segment-level read (`cache_lib.load_melt_landed_titles`), no full melt parse. Prints, for each wanted
cid, every title whose holder history records him, with the tenure dates and the title's key/name.
Usage: & tools\\py.ps1 tools\\tests\\v118_probe_landed.py [melt] [cid...]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import cache_lib as cl  # noqa: E402

DATA = ROOT / "output" / "洪氏2" / "data"
MELT = DATA / "melt_1285_01_01.json"
WANT = [38957, 44503, 67172818, 16879059, 16878235, 135480]


def tenure_of(rec, cid):
    """[(gain, loss, type)] for one holder id inside a title record's history."""
    out = []
    hist = rec.get("history") or {}
    if isinstance(hist, dict):
        items = hist.items()
    else:
        items = enumerate(hist or [])
    for _k, ev in items:
        if not isinstance(ev, dict):
            continue
        claim = ev.get("claim") or ev.get("holder") or ev.get("character")
        if claim is None:
            claim = (ev.get("holder") or {})
        if isinstance(claim, dict):
            claim = claim.get("id") or claim.get("character")
        try:
            claim = int(claim)
        except (TypeError, ValueError):
            continue
        if claim == cid:
            out.append((ev.get("date"), ev.get("type") or ev.get("event"),
                        {k: v for k, v in ev.items() if k not in ("holder",)}))
    return out


def main():
    melt = Path(sys.argv[1]) if len(sys.argv) > 1 else MELT
    want = [int(x) for x in sys.argv[2:]] or WANT
    lt = cl.load_melt_landed_titles(str(melt)) or {}
    titles = lt.get("landed_titles") or lt
    print(f"melt={melt.name} tiles={len(titles)}")
    loc_path = ROOT / "data" / "localization.json"
    loc = json.loads(loc_path.read_text(encoding="utf-8")) if loc_path.is_file() else {}
    for cid in want:
        print(f"\n===== cid {cid} =====")
        hits = 0
        for tid, rec in titles.items():
            if not isinstance(rec, dict):
                continue
            tus = tenure_of(rec, cid)
            if not tus:
                continue
            hits += 1
            key = rec.get("key") or ""
            name = loc.get(key) or loc.get(key + "_name") or ""
            print(f"-- {tid} key={key!r} name={name!r} tier={rec.get('tier')!r} "
                  f"de_facto_liege={rec.get('de_facto_liege')!r} "
                  f"landless={rec.get('landless')!r}")
            for t in sorted(tus, key=lambda x: cl.date_key(str(x[0]))):
                print(f"     {t[0]}  {t[1]}")
        if not hits:
            print("   (no title history entry)")


if __name__ == "__main__":
    main()
