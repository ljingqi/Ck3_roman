"""v118 probe: from the production cache alone, locate the 11th 刀下亡魂 (cid 321250) and its
name fields. Read-only, no melt load. Usage:
  & tools\\py.ps1 tools\\tests\\v118_probe_cache_kill.py [cache.json] [cid]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "output" / "洪氏2" / "data" / "player_17066495.json"


def main():
    cache_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CACHE
    cid = str(sys.argv[2]) if len(sys.argv) > 2 else "321250"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    pid = str(cache.get("player_id"))
    chars = cache.get("characters") or {}
    print(f"cache last_date={cache.get('last_date')} player={pid} chars={len(chars)}")
    print(f"player_death={json.dumps(cache.get('player_death'), ensure_ascii=False)[:400]}")
    prec = chars.get(pid) or {}
    kills = prec.get("kills") or []
    print(f"player kills n={len(kills)}; {cid} in kills: {int(cid) in [int(k) for k in kills]}")
    print(f"kills list={kills}")
    rec = chars.get(cid)
    print(f"\ncharacters[{cid}] present: {rec is not None}")
    if rec:
        print(json.dumps({k: rec.get(k) for k in
                          ("name_zh", "name_full", "dynasty_name", "house_name", "birth",
                           "death", "kills", "memories", "titles")}, ensure_ascii=False)[:1500])
    # who else has an empty/absent cache record but shows up in the player's death list
    dd = cache.get("player_death") or {}
    print(f"\nplayer_death keys={list(dd)}")
    print(f"death.kills={dd.get('kills')}")


if __name__ == "__main__":
    main()
