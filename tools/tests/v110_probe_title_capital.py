# -*- coding: utf-8 -*-
"""v110 dev probe: what does a title's `capital` field hold, and where does a seat resolve?

The v109 report left one question open (logs/v109/v109_victim_place_report.md §6): is
`landed_titles[tid]["capital"]` a **title id** (as `_capital_province_at` assumes) or a
**province id**? This probe loads one cache + melt and prints, for the given title ids,
the raw landed_titles record, its key, whether the key is in the province map, and where
the capital resolves under each reading.

Usage:
    & tools\\py.ps1 tools\\tests\\v110_probe_title_capital.py <folder> <pid> <tid> [tid…]
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402


def _melt_path(folder):
    data = os.path.join(ROOT, "output", folder, "data")
    melts = [x for x in os.listdir(data) if x.startswith("melt_") and "_idx" not in x]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key)), data


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    folder, pid, tids = sys.argv[1], int(sys.argv[2]), [int(x) for x in sys.argv[3:]]
    melt_path, data = _melt_path(folder)
    cache = json.load(open(os.path.join(data, "player_%d.json" % pid), encoding="utf-8"))
    print("载入熔件 %s" % os.path.basename(melt_path), flush=True)
    melt = cl.load_melt(melt_path)
    f = F.Facts(cache, melt, os.path.join(ROOT, "data", "names.json"))
    lt = f._lt
    inv = f._prov_inv()
    pm = f.provmap or {}
    print("landed_titles 条数 %d / province_map 条数 %d / _prov_inv 条数 %d / _ESTATE_KEY_MARK=%r"
          % (len(lt), len(pm), len(inv), F.Facts._ESTATE_KEY_MARK))
    for tid in tids:
        rec = lt.get(str(tid)) or {}
        key = rec.get("key") or ""
        cap = rec.get("capital")
        print("-" * 70)
        print("tid=%d key=%r capital=%r province=%r  estate=%s  rank=%s"
              % (tid, key, cap, rec.get("province"), f._is_estate_title(tid),
                 f._TT_RANK.get(key[:2], 0)))
        extra = {k: v for k, v in rec.items()
                 if k not in ("key", "capital", "province", "de_jure_liege")}
        print("   其余字段: %s" % json.dumps(extra, ensure_ascii=False)[:400])
        print("   key in _prov_inv → %r" % inv.get(key))
        print("   key in province_map values: %s" % [p for p, v in list(pm.items())[:0]])
        if isinstance(cap, int):
            crec = lt.get(str(cap)) or {}
            ckey = crec.get("key") or ""
            print("   capital 当 tid: _lt[%d] key=%r → _prov_inv %r ; 当省号: province_map[%d]=%r"
                  % (cap, ckey, inv.get(ckey), cap, pm.get(str(cap))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
