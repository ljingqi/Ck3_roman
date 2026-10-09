# -*- coding: utf-8 -*-
"""v117 check (item 4): the death-day anchor must survive a predecessor missing from the cache.

Runs the production `facts.py` on 洪光通's volume (player 17066495, melt_1283_01_01.json,
as_of 1283.9.11) with the full campaign, and compares every campaign subject's rendered label
before / after `Facts.death_date` (the "before" side restores the pre-v117 `_anchor_date` /
`_gen_end_date` bodies in memory only).

Assertions:
  [A] `_anchor_date(44503, '952.1.29')` folds to '952.1.28' (the day before death);
  [B] cid 44503's label reads 天皇帝… and no longer 前工部尚书…;
  [C] every other subject's label is byte-identical before/after.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_death_date.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl       # noqa: E402
import facts as F            # noqa: E402

FOLDER = "洪氏2"
PID = 17066495
MELT = "melt_1283_01_01.json"
AS_OF = "1283.9.11"
CID = 44503
LOG = os.path.join(ROOT, "logs", "v117_check_death_date.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def anchor_old(self, cid, date=None):
    """Pre-v117 `Facts._anchor_date` body, kept for the before/after comparison only."""
    rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
    dd = (rec.get("death") or {}).get("date")
    if not dd and cid == self.cache.get("player_id"):
        dd = (self.cache.get("player_death") or {}).get("date")
    if date:
        if dd and cl.date_key(date) >= cl.date_key(dd):
            return F._day_before(dd)
        return date
    if dd and (not self.as_of or cl.date_key(dd) <= cl.date_key(self.as_of)):
        return F._day_before(dd)
    return self.as_of


def gen_end_old(f, cid):
    """Pre-v117 `_gen_end_date` body, kept for the before/after comparison only."""
    rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
    d = (rec.get("death") or {}).get("date") or ""
    if d:
        return d
    pv = f.campaign.get(int(cid)) if str(cid).isdigit() else None
    if isinstance(pv, dict):
        for key in ("reign_end", "player_death"):
            v = pv.get(key)
            if isinstance(v, dict) and v.get("date"):
                return v["date"]
    return ""


def main():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache = json.load(open(os.path.join(data, f"player_{PID}.json"), encoding="utf-8"))
    melt = cl.load_melt(os.path.join(data, MELT))
    names = os.path.join(data, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    campaign = {}
    for fn in os.listdir(data):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        try:
            c = json.load(open(os.path.join(data, fn), encoding="utf-8"))
        except Exception:
            continue
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(m.group(1))] = c
    f = F.Facts(cache, melt, names, as_of=AS_OF, decade=None, campaign=campaign or None)
    prec = (cache.get("characters") or {}).get(str(PID)) or {}
    w(f"[{MELT} as_of={AS_OF}] subject={prec.get('name')} campaign subjects={len(campaign)}")

    w(f"  [A] _anchor_date({CID}, '952.1.29') = {f._anchor_date(CID, '952.1.29')!r}")
    ok_a = f._anchor_date(CID, "952.1.29") == "952.1.28"

    def table(inst):
        rows = []
        for cid in campaign:
            end = F._gen_end_date(inst, cid) or ""
            rows.append((end, cid, inst.person_label(cid, end, "full")))
        rows.sort(key=lambda r: (cl.date_key(r[0]) if r[0] else (), str(r[1])))
        return rows

    # One fresh `Facts` per side: the instance memoizes per-(cid, date) renders, so reusing a single
    # instance would let the "after" values leak into the "before" pass.
    F.Facts._anchor_date = anchor_old
    F._gen_end_date = gen_end_old
    try:
        before = table(F.Facts(json.loads(json.dumps(cache)), melt, names, as_of=AS_OF,
                               decade=None, campaign=campaign or None))
    finally:
        F.Facts._anchor_date = _ANCHOR_NEW
        F._gen_end_date = _GEN_END_NEW
    after = table(F.Facts(json.loads(json.dumps(cache)), melt, names, as_of=AS_OF,
                          decade=None, campaign=campaign or None))

    w("  cid           日付      改前                                 改后                                变?")
    changed = []
    for (e1, c1, l1), (e2, c2, l2) in zip(before, after):
        same = (l1 == l2 and e1 == e2)
        if not same:
            changed.append((c1, e1, l1, e2, l2))
        w(f"  {c1:>10} {e1:<10} {l1:<36} {l2:<36} {'—' if same else '变化'}")
    w(f"\n  changed subjects = {[(c, a, b) for c, _e, _l, a, b in changed]}")
    hit = [x for x in changed if x[0] == CID]
    ok_b = bool(hit) and "天皇帝" in hit[0][4] and "前工部尚书" not in hit[0][4]
    # Two subjects are expected to move, both because a character is now read inside his own life:
    #   44503    -- the v117 ④ report (record absent from the cache, melt carries the death day);
    #   16878235 -- his parent 84824 (洪仁德, 山南观察使, d.973.3.27) is now anchored in 973 instead
    #               of 1009, so the government word comes from the parent's own life: the code's own
    #               note at facts.py:10235-10247 calls the earlier 山南王子 a feudal word that the
    #               character side is meant to replace with the administrative one (山南公子).
    # Anything else changing is a regression.
    expected = {CID: ("天皇帝",), 16878235: ("山南公子",)}
    ok_c = ({x[0] for x in changed} == set(expected)
            and all(any(t in x[4] for t in expected[x[0]]) for x in changed))

    w("")
    for name, cond in (("[A] 卒日前一天回折", ok_a),
                       ("[B] 44503 头衔恢复为天皇帝", ok_b),
                       ("[C] 只有预期的两位传主变化（44503／16878235）", ok_c)):
        w(f"  {'PASS' if cond else 'FAIL'} {name}")
    ok = ok_a and ok_b and ok_c
    w(f"\n[{'PASS' if ok else 'FAIL'}] v117 ④ death-date check")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if ok else 1)


# Production bodies captured at import time, so the before/after comparison can restore them.
_ANCHOR_NEW = F.Facts._anchor_date
_GEN_END_NEW = F._gen_end_date

if __name__ == "__main__":
    main()
