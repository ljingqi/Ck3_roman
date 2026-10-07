# -*- coding: utf-8 -*-
"""v111 定点核对：几个头衔在若干日期上的名字（含族名伪影判定）。

用法：
    & tools\\py.ps1 tools\\tests\\v111_check_title_names.py <家族> <pid> [<家族> <pid> ...]
默认核对 d_liaoxi(12722) 与两处州(15686 邕州 / 15236 通州)。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402

CASES = [(12722, ["1107.1.1", "1144.6.20", "1147.8.14", "1150.1.1", "1155.1.1"]),
         (15686, ["1109.4.25"]),
         (15236, ["1120.1.1", "1126.7.29", "1126.7.30"])]


def _melt_path(folder):
    data = os.path.join(ROOT, "output", folder, "data")
    melts = [x for x in os.listdir(data) if x.startswith("melt_") and "_idx" not in x]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key)), data


def main():
    folder, pid = sys.argv[1], int(sys.argv[2])
    melt_path, data = _melt_path(folder)
    print("# melt=%s pid=%d" % (os.path.basename(melt_path), pid), flush=True)
    melt = cl.load_melt(melt_path)
    cache = cl.load_cache(os.path.join(data, "player_%d.json" % pid))
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, melt, names_path)
    for tid, dates in CASES:
        t = f._lt.get(str(tid)) or {}
        tnd = t.get("title_name_data") or {}
        print("\n## tid=%s key=%s  name=%r custom=%r specific=%r" % (
            tid, t.get("key"), tnd.get("name"), tnd.get("custom"),
            tnd.get("specific_title_name")))
        print("   people_names=%s  dyn_hist=%s  specific_name=%r  base=%r" % (
            sorted(f._people_names(tid)), f._dyn_hist(tid), f._specific_name(tid),
            f.title_base_name(tid)))
        for d in dates:
            print("   %-11s holder=%-10s keeps_people=%-5s _name_at_date=%-10s "
                  "history_name=%-26s office_text(pid=%d)=%s" % (
                      d, f.holder_at(tid, d), f._keeps_people_name(tid, d),
                      f._name_at_date(tid, d), f._history_name_at(tid, d), pid,
                      f.title_office_text(pid, tid, d)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
