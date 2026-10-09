"""v118 probe: for every played-chain character, what the cache holds vs what the melt holds.

Reads the cache once (280 MB JSON) plus segment-level melt sections (no full melt parse).
Usage: & tools\\py.ps1 tools\\tests\\v118_probe_chain_cover.py [years...]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import cache_lib as cl  # noqa: E402

DATA = ROOT / "output" / "洪氏2" / "data"
CACHE = DATA / "player_17066495.json"


def main():
    years = sys.argv[1:] or ["1283", "1285"]
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    chain = [e["cid"] for e in cache.get("played_legacy") or []]
    chars = cache.get("characters") or {}
    print(f"chain={chain}")
    melts = {}
    for y in years:
        p = DATA / f"melt_{y}_01_01.json"
        if not p.is_file():
            continue
        live = cl.load_melt_section(str(p), "living") or {}
        dead = cl.load_melt_section(str(p), "dead_unprunable") or {}
        cch = cl.load_melt_section(str(p), "characters") or {}
        dp = (cch.get("dead_prunable") or {}) if isinstance(cch, dict) else {}
        melts[y] = (live, dead, dp)
        print(f"melt {y}: living={len(live)} dead_unprunable={len(dead)} dead_prunable={len(dp)}")
    for cid in chain:
        rec = chars.get(str(cid))
        bits = [f"cid={cid}"]
        bits.append("cache=Y" if rec else "cache=N")
        if rec:
            fam = rec.get("family") or {}
            bits.append(f"birth={rec.get('birth')!r}")
            bits.append(f"death={(rec.get('death') or {}).get('date')!r}")
            bits.append("fam=[" + ",".join(k for k, v in fam.items() if v) + "]")
            bits.append("name=" + repr(rec.get("name_zh") or rec.get("name_full")))
        for y, (live, dead, dp) in melts.items():
            r = live.get(str(cid)) or dead.get(str(cid)) or dp.get(str(cid))
            if not isinstance(r, dict):
                bits.append(f"{y}=absent")
                continue
            where = ("L" if str(cid) in live else ("D" if str(cid) in dead else "P"))
            fd = r.get("family_data") or r.get("family") or {}
            bits.append(f"{y}={where} birth={r.get('birth')!r} "
                        f"dead={(r.get('dead_data') or {}).get('date')!r} "
                        f"fam=[" + ",".join(k for k, v in fd.items() if v) + "]")
        print("  " + " | ".join(bits))


if __name__ == "__main__":
    main()
