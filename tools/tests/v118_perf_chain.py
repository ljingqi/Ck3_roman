"""v118 timing: how long does the played-chain overlay cost per facts build?

Usage: & tools\\py.ps1 tools\\tests\\v118_perf_chain.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import facts as FT  # noqa: E402

DATA = ROOT / "output" / "洪氏2" / "data"


def main():
    own = json.loads((DATA / "player_17066495.json").read_text(encoding="utf-8"))
    camp = {}
    for pid in (38957, 44503, 67172818, 16879059, 16878235):
        camp[pid] = json.loads((DATA / f"player_{pid}.json").read_text(encoding="utf-8"))
    print("campaign caches:", list(camp))
    for i in range(3):
        t0 = time.time()
        out = FT._with_campaign_chain(own, camp)
        dt = time.time() - t0
        print("  run%d: %.0f ms, characters %d -> %d"
              % (i + 1, dt * 1000, len(own["characters"]), len(out["characters"])))
    t0 = time.time()
    same = FT._with_campaign_chain(own, {})
    print("  no campaign: %.2f ms, same object=%s"
          % ((time.time() - t0) * 1000, same is own))


if __name__ == "__main__":
    main()
