# -*- coding: utf-8 -*-
"""v111 影响面：`specific_title_name` 非空且与静态名不同的头衔，按持有者政体/头衔种类分类。

用来判断「定居持有者改用静态名」这条规则会波及哪些头衔（营地、庄园、游牧毡帐…）。

用法：
    & tools\\py.ps1 tools\\tests\\v111_impact_specific_names.py <家族> <pid> [<日期>]
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402


def _melt_path(folder):
    data = os.path.join(ROOT, "output", folder, "data")
    melts = [x for x in os.listdir(data) if x.startswith("melt_") and "_idx" not in x]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key)), data


def main():
    folder, pid = sys.argv[1], int(sys.argv[2])
    date = sys.argv[3] if len(sys.argv) > 3 else "1144.6.20"
    melt_path, data = _melt_path(folder)
    print("# melt=%s pid=%d date=%s" % (os.path.basename(melt_path), pid, date), flush=True)
    melt = cl.load_melt(melt_path)
    cache = cl.load_cache(os.path.join(data, "player_%d.json" % pid))
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, melt, names_path)
    stat = collections.Counter()
    kinds = collections.Counter()
    rows = []
    for tid, t in ((melt.get("landed_titles") or {}).get("landed_titles") or {}).items():
        if not isinstance(t, dict):
            continue
        tnd = t.get("title_name_data") or {}
        sp = (tnd.get("specific_title_name") or "").strip()
        nm = (tnd.get("name") or "").strip()
        cu = (tnd.get("custom") or "").strip()
        if not sp or sp == nm or cu:
            continue
        keeps = f._keeps_people_name(tid, date)
        kind = f.title_kind(tid)
        stat[("kept" if keeps else "dropped",
              "reign_hist" if f._has_reign_history(tid) else "no-reign",
              kind)] += 1
        kinds[kind] += 1
        if len(rows) < 30:
            rows.append((tid, t.get("key"), nm, sp, kind, keeps, f.holder_at(tid, date)))
    print("#### specific≠name 且无 custom 的头衔：%d 个（title_kind 分布 %s）"
          % (sum(stat.values()), dict(kinds)))
    for k, n in stat.most_common(20):
        print("   %-46s %d" % (str(k), n))
    print("\n#### 抽样 30")
    for tid, key, nm, sp, kind, keeps, hid in rows:
        print("   tid=%-8s key=%-22s kind=%-9s %s -> %s (keeps=%s holder=%s)" % (
            tid, key, kind, sp, nm, keeps, hid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
