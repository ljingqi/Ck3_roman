# -*- coding: utf-8 -*-
"""v111 影响面：族名（`<culture>_collective_noun`）在改动后是否被静态名取代。

对每个名史里带族名的头衔，比较「改动前会用的动态名」与「改动后 `_name_at_date` 给的名字」，
并按持有者政体（游牧/部落/牧人 保留族名，定居改用静态名）分类计数。

用法：
    & tools\\py.ps1 tools\\tests\\v111_impact_people_names.py <家族> <pid> [<日期>]
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402
import localization as L    # noqa: E402


def _melt_path(folder):
    data = os.path.join(ROOT, "output", folder, "data")
    melts = [x for x in os.listdir(data) if x.startswith("melt_") and "_idx" not in x]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key)), data


def main():
    folder, pid = sys.argv[1], int(sys.argv[2])
    date = sys.argv[3] if len(sys.argv) > 3 else None
    melt_path, data = _melt_path(folder)
    print("# melt=%s pid=%d date=%s" % (os.path.basename(melt_path), pid, date or "(最后存档)"),
          flush=True)
    melt = cl.load_melt(melt_path)
    cache = cl.load_cache(os.path.join(data, "player_%d.json" % pid))
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, melt, names_path)
    d = date or f.as_of or cache.get("last_date")

    stat = collections.Counter()
    rows = []
    for tid, t in (melt.get("landed_titles") or {}).get("landed_titles", {}).items():
        if not isinstance(t, dict):
            continue
        ppl = f._people_names(tid)
        if not ppl:
            continue
        tnd = t.get("title_name_data") or {}
        nm = (tnd.get("name") or "").strip()
        sp = (tnd.get("specific_title_name") or "").strip()
        hist = [h for h in (tnd.get("title_history_names") or []) if isinstance(h, dict)]
        before = ""
        if hist:
            last = max(hist, key=lambda h: str(h.get("date") or ""))
            before = (L.loc(f.table, str(last.get("name") or "")) or "").strip()
        if not before and sp:
            before = sp
        after = f._name_at_date(tid, d) or f.title_base_name(tid)
        keeps = f._keeps_people_name(tid, d)
        stat[("kept" if keeps else "suppressed",
              "changed" if before and before != after else "same")] += 1
        if len(rows) < 20 and before != after:
            rows.append((tid, t.get("key"), nm, sp, before, after, keeps,
                         f.holder_at(tid, d)))
    print("#### 带族名的头衔：%d 个" % sum(stat.values()))
    for k, n in stat.most_common():
        print("   %-28s %d" % (str(k), n))
    print("\n#### 抽样（名字真的变了的前 20 个）")
    for tid, key, nm, sp, before, after, keeps, hid in rows:
        print("   tid=%-8s key=%-22s name=%-10s specific=%-10s %s -> %s (keeps=%s holder=%s)" % (
            tid, key, nm, sp or "-", before, after, keeps, hid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
