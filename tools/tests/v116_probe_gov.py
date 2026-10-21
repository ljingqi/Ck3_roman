# -*- coding: utf-8 -*-
"""v116 取证 2：父之政体到底从哪来（为何快照给「山南观察使」而探针 1 给「山南王」）。

打印：`_chars['84824']` 的 dead_data 关键字段、`_gov_for_word`、`_dead_flavor_consistent`、
`official_title` 在 `date=None` 与 `date=1152.11.13` 两种读法下的结果。
同样对 177780（洪因）、44503（洪天贵福）、38957（洪秀全）各来一遍。

用法：python -X utf8 tools/tests/v116_probe_gov.py [--peers=...]
输出：logs/v116/v116_probe_gov.txt
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402

FOLDER = "洪氏2"
PID = 207044
AS_OF = "1152.11.13"
CIDs = [84824, 177780, 44503, 38957]


def melt_path():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    if os.environ.get("V116_MELT"):
        return os.environ["V116_MELT"], data
    melts = [x for x in os.listdir(data) if x.startswith("melt_") and "_idx" not in x]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key)), data


def main():
    peers = {}
    for a in sys.argv[1:]:
        if a.startswith("--peers="):
            for x in a.split("=", 1)[1].split(","):
                x = x.strip()
                if x.isdigit():
                    p = os.path.join(ROOT, "output", FOLDER, "data", "player_%s.json" % x)
                    if os.path.exists(p):
                        peers[int(x)] = json.load(io.open(p, encoding="utf-8"))
    mp, data = melt_path()
    print("熔件 %s" % os.path.basename(mp), flush=True)
    melt = cl.load_melt(mp)
    cache = json.load(io.open(os.path.join(data, "player_%d.json" % PID), encoding="utf-8"))
    f = F.Facts(cache, melt, os.path.join(data, "names.json"), campaign=peers)
    print("melt 段: %s" % sorted(melt.keys()))
    ch = cache.get("characters") or {}

    def nm(cid):
        r = ch.get(str(cid)) or {}
        return "%s(%s)" % (r.get("name_full") or "?", cid)

    for cid in CIDs:
        print("\n===== %s" % nm(cid))
        c = f._chars.get(str(cid)) or {}
        print("  _chars 命中: %s；键=%s" % (bool(c), sorted(c.keys())[:14]))
        dd = c.get("dead_data") or {}
        print("  dead_data: date=%r government=%r flavor=%r liege=%r"
              % (dd.get("date"), dd.get("government"), dd.get("flavor"), dd.get("liege")))
        print("  landed_data: %s" % json.dumps(c.get("landed_data") or {}, ensure_ascii=False)[:200])
        for dt in (None, AS_OF):
            anchor = f._anchor_date(cid, dt)
            print("  -- date=%r anchor=%s" % (dt, anchor))
            print("     _character_government=%r  _gov_for_word(tid=%r)=%r"
                  % (f._character_government(cid, anchor),
                     None, f._gov_for_word(cid, None, anchor)))
            t, tid = f._primary_title_at(cid, as_of=anchor)
            print("     _primary_title_at=(%s,%s)  _title_government=%r  _title_government_hist=%r"
                  % (t, tid, f._title_government(tid, anchor) if tid else "",
                     f._title_government_hist(tid, anchor) if tid else ""))
            print("     _dead_flavor_consistent(fkey=%r)=%s"
                  % (dd.get("flavor"),
                     f._dead_flavor_consistent(dd.get("flavor"), cid, anchor) if dd.get("flavor")
                     else "无 fkey"))
            print("     official_title=%r" % f.official_title(cid, dt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
