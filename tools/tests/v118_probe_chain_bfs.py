"""v118 probe: can the played chain's early generations be rebuilt from the campaign caches?

The 世系 heads of the last volume lose 生年/亲属词 for the generations whose records the last
volume's cache does not carry. This probe (1) BFS-walks the family graph of the chain over the
campaign caches that played those generations, (2) counts the closure, and (3) recomputes the
kinship word and the blood-generation gap with the project's own functions to check them against
the older volumes' published 世系 (二世→四世 = +2, 四世→四世 = 0).

Usage: & tools\\py.ps1 tools\\tests\\v118_probe_chain_bfs.py
"""
import json
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import facts as FT  # noqa: E402

DATA = ROOT / "output" / "洪氏2" / "data"
CACHE = DATA / "player_17066495.json"
# the volumes that played the early generations (their caches hold those people as kin)
EARLY = ["player_38957.json", "player_44503.json", "player_67172818.json",
         "player_16879059.json", "player_16878235.json"]
FAM_KEYS = ("father", "real_father", "mother", "siblings", "child",
            "primary_spouse", "spouse", "former_spouses", "concubine",
            "former_concubines", "ever_spouses")
MAX_DEPTH = 6
CAP = 20000


def main():
    own = (json.loads(CACHE.read_text(encoding="utf-8")).get("characters") or {})
    pool = {}
    for fn in EARLY:
        p = DATA / fn
        if not p.is_file():
            continue
        t0 = time.time()
        ch = json.loads(p.read_text(encoding="utf-8")).get("characters") or {}
        for cid, rec in ch.items():
            pool.setdefault(cid, rec)
        print(f"{fn}: {len(ch)} chars, {time.time() - t0:.1f}s")
    print(f"own cache: {len(own)} chars; pool: {len(pool)}")

    chain = [e["cid"] for e in json.loads(CACHE.read_text(encoding="utf-8"))["played_legacy"]]
    print("chain:", chain)

    def rec_of(cid):
        return own.get(str(cid)) or pool.get(str(cid))

    extra, seen, frontier = {}, set(), []
    for cid in chain:
        if cid not in seen:
            seen.add(cid)
            frontier.append((cid, 0))
    while frontier:
        cid, d = frontier.pop()
        r = rec_of(cid)
        if not isinstance(r, dict):
            continue
        if str(cid) not in own:
            extra[cid] = r
        if d >= MAX_DEPTH or len(extra) > CAP:
            continue
        fam = r.get("family") or {}
        for k in FAM_KEYS:
            for x in (fam.get(k) or []):
                if isinstance(x, int) and x not in seen:
                    seen.add(x)
                    frontier.append((x, d + 1))
    print(f"closure: {len(seen)} people, {len(extra)} records not in the last volume's cache")
    for nm, cid in (("洪天香", 45152), ("洪地香", 16836925),
                    ("洪天碧", 47113), ("洪地保", 33611550)):
        print(f"  {nm}({cid}): in extra={cid in extra} in own={str(cid) in own}")

    merged = dict(own)
    merged.update({str(k): v for k, v in extra.items()})
    shim = types.SimpleNamespace(cache={"characters": merged}, _pedges=None, _chars={})
    shim._parent_edges = lambda: FT.Facts._parent_edges(shim)
    shim._up_routes = lambda cid: FT.Facts._up_routes(shim, cid)
    GEN = {38957: 1, 44503: 2, 67172818: 3, 16879059: 4, 16878235: 5,
           135480: 6, 117484775: 7, 16945142: 8, 207044: 9}
    print("\n== kinship words / generation gaps over the merged characters ==")
    for a, b in zip(chain, chain[1:]):
        key = FT.kin_key({"characters": merged}, a, b)
        d = FT.Facts.generation_delta(shim, a, b)
        print(f"  {a} -> {b}: delta={d!r} word={FT.kin_word_short(key)!r} key={key!r} "
              f"(own-only: delta={FT.Facts.generation_delta(_shim(own), a, b)!r} "
              f"word={FT.kin_word_short(FT.kin_key({'characters': own}, a, b))!r})")


def _shim(chars):
    s = types.SimpleNamespace(cache={"characters": chars}, _pedges=None, _chars={})
    s._parent_edges = lambda: FT.Facts._parent_edges(s)
    s._up_routes = lambda cid: FT.Facts._up_routes(s, cid)
    return s


if __name__ == "__main__":
    main()
