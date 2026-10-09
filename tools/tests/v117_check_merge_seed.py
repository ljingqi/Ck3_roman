# -*- coding: utf-8 -*-
"""v117 check (item 4c): the merge target set keeps every 传主 of the campaign chain.

Asserts that `cache_lib._merge_seed` includes cid 44503 — a predecessor of ANOTHER branch of the
same dynasty (house 12295 vs the player's 31062), which the house test alone cannot see — while
still keeping the player, his family and his own house exactly as before.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_merge_seed.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl       # noqa: E402

FOLDER = "洪氏2"
PID = 17066495
MELT = "melt_1283_01_01.json"
CID = 44503
LOG = os.path.join(ROOT, "logs", "v117_check_merge_seed.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def old_seed(chars, player_id):
    """The pre-v117 seed: player + family + own house only."""
    targets = set()
    targets.add(player_id)
    p = chars.get(str(player_id))
    if p:
        for ids in cl.family_of(p).values():
            targets.update(ids)
        house = p.get("dynasty_house")
        if house is not None:
            for cid, c in chars.items():
                if isinstance(c, dict) and c.get("dynasty_house") == house:
                    targets.add(int(cid))
    return targets


def main():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache = json.load(open(os.path.join(data, f"player_{PID}.json"), encoding="utf-8"))
    melt = cl.load_melt(os.path.join(data, MELT))
    chars = cl.all_characters(melt)
    seed = cl._merge_seed(cache, chars, PID)
    before = old_seed(chars, PID)
    chain = [e.get("cid") for e in (cache.get("played_legacy") or [])]

    ph = (chars.get(str(PID)) or {}).get("dynasty_house")
    ch44503 = (chars.get(str(CID)) or {}).get("dynasty_house")
    w(f"player {PID} house={ph}; cid {CID} house={ch44503}")
    w(f"chain ({len(chain)}): {chain}")
    w(f"seed={len(seed)}  old={len(before)}  added={sorted(seed - before)}")
    w(f"dropped by the change: {sorted(before - seed)}")

    a = PID in seed and CID in seed
    b = ch44503 != ph and CID not in before          # the house test alone really misses him
    c = all(e in seed for e in chain if isinstance(e, int))
    d = before <= seed                               # nothing the old rule collected is lost
    w("")
    for name, cond in (("[A] 玩家本人与 44503 都在目标集内", a),
                       ("[B] 44503 与玩家不同房，旧口径确实漏掉他", b),
                       ("[C] 传主链全员入集", c),
                       ("[D] 旧口径收的人一个不少", d)):
        w(f"  {'PASS' if cond else 'FAIL'} {name}")
    ok = a and b and c and d
    w(f"\n[{'PASS' if ok else 'FAIL'}] v117 ④c merge-seed check")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
