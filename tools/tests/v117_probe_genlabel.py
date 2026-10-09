# -*- coding: utf-8 -*-
"""v117 ④ side check: why does 16878235's genealogy head read 山南王子 / 山南公子?

The v117 death-date change folds the head date to the day before death for every campaign
subject (not only the one whose record was missing), which flips 16878235 from 山南王子 to
山南公子. This prints the evidence behind both readings: his own title intervals and his
father's, at the death day and the day before.

Usage: & tools\\py.ps1 tools\\tests\\v117_probe_genlabel.py
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
CID = 16878235
LOG = os.path.join(ROOT, "logs", "v117_probe_genlabel.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


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
    ch = f._chars
    rec = ch.get(str(CID)) or {}
    w(f"cid {CID}: house={rec.get('dynasty_house')} father={rec.get('father')} "
      f"mother={rec.get('mother')}")
    w(f"  campaign cache: {(campaign.get(CID) or {}).get('player_death')} "
      f"reign_end={(campaign.get(CID) or {}).get('reign_end')}")
    bg = f.cache.get("characters", {}).get(str(CID)) or {}
    w(f"  洪光通 cache record: death={bg.get('death')}")
    for d in ("1009.6.25", "1009.6.26", AS_OF):
        w(f"  @{d}: anchor={f._anchor_date(CID, d)} primary={f._primary_title_at(CID, as_of=d)}")
        w(f"            person_label(full)={f.person_label(CID, d, 'full')!r}")
    w("  own held-title intervals:")
    for tid, ivs in sorted(f._hold_intervals(CID).items()):
        w(f"    {tid} {f.title_base_name(tid)} {ivs}")

    fid = rec.get("father") if isinstance(rec.get("father"), int) else None

    # Same reads with the pre-v117 `_anchor_date` body (cache record only, no campaign/melt fallback).
    def anchor_old(self, cid, date=None):
        r = (self.cache.get("characters") or {}).get(str(cid)) or {}
        dd = (r.get("death") or {}).get("date")
        if not dd and cid == self.cache.get("player_id"):
            dd = (self.cache.get("player_death") or {}).get("date")
        if date:
            if dd and cl.date_key(date) >= cl.date_key(dd):
                return F._day_before(dd)
            return date
        if dd and (not self.as_of or cl.date_key(dd) <= cl.date_key(self.as_of)):
            return F._day_before(dd)
        return self.as_of

    _new = F.Facts._anchor_date
    F.Facts._anchor_date = anchor_old
    try:
        f_old = F.Facts(json.loads(json.dumps(cache)), melt, names, as_of=AS_OF,
                        decade=None, campaign=campaign or None)
        w("\n  [pre-v117 _anchor_date]")
        for d in ("1009.6.25", "1009.6.26", AS_OF):
            w(f"  @{d}: anchor={f_old._anchor_date(CID, d)}"
              f" primary={f_old._primary_title_at(CID, as_of=d)}"
              f" label={f_old.person_label(CID, d, 'full')!r}")
    finally:
        F.Facts._anchor_date = _new

    if fid is not None:
        frec = ch.get(str(fid)) or {}
        w(f"\nfather {fid}: house={frec.get('dynasty_house')} death={(frec.get('dead_data') or {}).get('date')}")
        for d in ("1009.6.25", "1009.6.26", AS_OF):
            w(f"  @{d}: anchor={f._anchor_date(fid, d)} primary={f._primary_title_at(fid, as_of=d)}"
              f" label={f.person_label(fid, d, 'full')!r}")

    # Which `_anchor_date` calls differ between the two bodies? Trace both renderings of the label.
    def traced(base, sink):
        def _f(self, cid, date=None):
            r = base(self, cid, date)
            sink.append((cid, date, r))
            return r
        return _f

    calls_new, calls_old = [], []
    F.Facts._anchor_date = traced(_new, calls_new)
    try:
        f_a = F.Facts(json.loads(json.dumps(cache)), melt, names, as_of=AS_OF,
                      decade=None, campaign=campaign or None)
        la = f_a.person_label(CID, "1009.6.26", "full")
    finally:
        F.Facts._anchor_date = traced(anchor_old, calls_old)
    try:
        f_b = F.Facts(json.loads(json.dumps(cache)), melt, names, as_of=AS_OF,
                      decade=None, campaign=campaign or None)
        lb = f_b.person_label(CID, "1009.6.26", "full")
    finally:
        F.Facts._anchor_date = _new
    w(f"\n  traced render: new={la!r} old={lb!r}")
    w(f"  anchor calls: new={len(calls_new)} old={len(calls_old)}")
    for i, (a, b) in enumerate(zip(calls_new, calls_old)):
        if a != b:
            w(f"    #{i} new={a}  old={b}")
    if len(calls_new) != len(calls_old):
        w("    call counts differ; tails:")
        w(f"      new tail={calls_new[len(calls_old):][:4]}")
        w(f"      old tail={calls_old[len(calls_new):][:4]}")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")


if __name__ == "__main__":
    main()
