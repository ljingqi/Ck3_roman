"""v118 check · fix B: the played chain's records come back from the campaign caches.

Builds the campaign map from the volumes that played the early generations, runs
`facts._with_campaign_chain`, and recomputes the kinship word and the blood-generation gap of every
consecutive pair. The values must equal the ones the older volumes published in 《世系》
(二世→四世 = +2 外甥孙, 四世→四世 = 0 再从表弟, 四世→四世 = 0 兄).

Usage: & tools\\py.ps1 tools\\tests\\v118_check_fix_b.py
"""
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import facts as FT               # noqa: E402

DATA = ROOT / "output" / "洪氏2" / "data"
CACHE = DATA / "player_17066495.json"
PLAYED = [38957, 44503, 67172818, 16879059, 16878235, 135480]
# 世次 the older volumes printed for the same chain: chain cid -> generation
WANT_DELTA = {(44503, 67172818): 2, (67172818, 16879059): 0, (16879059, 16878235): 0}
WANT_WORD = {(44503, 67172818): "外甥孙", (67172818, 16879059): "再从表弟",
             (16879059, 16878235): "兄"}


def _shim(chars):
    s = types.SimpleNamespace(cache={"characters": chars}, _pedges=None, _chars={})
    s._parent_edges = lambda: FT.Facts._parent_edges(s)
    s._up_routes = lambda cid: FT.Facts._up_routes(s, cid)
    return s


def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    campaign = {}
    for pid in PLAYED:
        p = DATA / f"player_{pid}.json"
        if p.is_file():
            campaign[pid] = json.loads(p.read_text(encoding="utf-8"))
    chain = [e["cid"] for e in cache["played_legacy"]]
    merged = FT._with_campaign_chain(cache, campaign)
    before = cache.get("characters") or {}
    after = merged.get("characters") or {}
    added = [c for c in chain if str(c) not in before and str(c) in after]
    print(f"chain={len(chain)} added_chain=({len(added)}) {added}")
    print(f"characters {len(before)} -> {len(after)} (+{len(after) - len(before)})")
    bad = 0
    for a, b in zip(chain, chain[1:]):
        sh = _shim(after)
        d = FT.Facts.generation_delta(sh, a, b)
        w = FT.kin_word_short(FT.kin_key({"characters": after}, a, b))
        d0 = FT.Facts.generation_delta(_shim(before), a, b)
        w0 = FT.kin_word_short(FT.kin_key({"characters": before}, a, b))
        flag = ""
        if (a, b) in WANT_DELTA:
            if d != WANT_DELTA[(a, b)] or w != WANT_WORD[(a, b)]:
                flag = "  <-- MISMATCH"
                bad += 1
        print(f"  {a} -> {b}: delta {d0} -> {d} word {w0 or '—'} -> {w or '—'}{flag}")
    print("FIX-B CHECK:", "PASS" if not bad else f"FAIL ({bad})")


if __name__ == "__main__":
    main()
