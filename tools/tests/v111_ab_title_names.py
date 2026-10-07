# -*- coding: utf-8 -*-
"""v111 头衔名 A/B：全量头衔在固定日期的名字（改动前后各跑一次再 diff）。

用法：
    & tools\\py.ps1 tools\\tests\\v111_ab_title_names.py <家族> <pid> <日期> > logs\\x.txt
另打印若干样本头衔的完整名史/动态名，便于人工核对。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402
import localization as L    # noqa: E402

DUMP = ["12722", "637", "650", "784", "791"]


def _melt_path(folder):
    data = os.path.join(ROOT, "output", folder, "data")
    melts = [x for x in os.listdir(data) if x.startswith("melt_") and "_idx" not in x]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key)), data


def main():
    folder, pid, date = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    melt_path, data = _melt_path(folder)
    print("# melt=%s pid=%d date=%s" % (os.path.basename(melt_path), pid, date), flush=True)
    melt = cl.load_melt(melt_path)
    cache = cl.load_cache(os.path.join(data, "player_%d.json" % pid))
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, melt, names_path)
    lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}
    for tid, t in sorted(lt.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
        if not isinstance(t, dict):
            continue
        try:
            nm = f._name_at_date(tid, date)
            base = f.title_base_name(tid)
            hist = f._history_name_at(tid, date)
        except Exception as e:
            nm = base = hist = "!!%s" % e
        print("%-8s %-26s %-14s %-14s %-24s" % (tid, t.get("key"), nm, base, hist))
    sys.stdout.flush()
    if os.environ.get("V111_NODUMP"):
        return 0
    for tid in DUMP:
        t = lt.get(tid) or {}
        tnd = t.get("title_name_data") or {}
        print("\n## dump tid=%s key=%s holder=%s" % (tid, t.get("key"), t.get("holder")))
        print("   name=%r custom=%r specific=%r map=%r" % (
            tnd.get("name"), tnd.get("custom"), tnd.get("specific_title_name"),
            tnd.get("specific_map_name")))
        for h in (tnd.get("title_history_names") or []):
            k = str((h or {}).get("name") or "")
            print("   hist %-14s %-30s loc=%s" % ((h or {}).get("date"), k, L.loc(f.table, k)))
        print("   dyn_hist=%s" % f._dyn_hist(tid))
        print("   holder_at=%s keeps_people=%s" % (
            f.holder_at(tid, date), f._keeps_people_name(tid, date)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
