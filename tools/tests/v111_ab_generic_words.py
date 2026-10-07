# -*- coding: utf-8 -*-
"""v111 量化：裸档位词（count/duke/...）的死者，究竟能不能问出更好的词。

对每个 dead_data.flavor 是裸档位词的死者，打印该人 anchor 当日的政体、
不带地名的 `_office_word`（政体词）、`_primary_title_at` 解出的头衔与地名，
用来决定「跳过裸词后」应该落到哪种口径。

用法：
    & tools\\py.ps1 tools\\tests\\v111_ab_generic_words.py <家族> <pid>
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402

BARE = {"hegemon", "emperor", "king", "duke", "count", "baron", "prince", "princess"}


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

    stat = collections.Counter()
    rows = []
    for cid, c in cl.all_characters(melt).items():
        if not isinstance(c, dict):
            continue
        dd = c.get("dead_data") or {}
        if str(dd.get("flavor") or "") not in BARE or not dd.get("date"):
            continue
        anchor = f._anchor_date(cid, dd["date"])
        tier, tid = f._primary_title_at(cid, as_of=anchor)
        gov = f._gov_for_word(cid, tid, anchor) if tid else f._character_government(cid, anchor)
        word = ""
        if tier:
            word = f._office_word(tier, gov,
                                  independent=bool(f._is_independent(cid, anchor)),
                                  female=f._is_female(cid),
                                  tid=tid, cid=cid, date=anchor)
        place = f._last_title_place(cid, dd.get("flavor") or "", date=anchor)
        stat[("title" if tid else "no-title", "gov" if gov else "no-gov",
              "word" if word else "no-word")] += 1
        if len(rows) < 60:
            rows.append((cid, dd["flavor"], anchor, gov, tier, tid, word, place))
    print("#### 组合计数 (title?, gov?, office_word?) -> %d 人" % sum(stat.values()))
    for k, n in stat.most_common():
        print("   %-38s %d" % (str(k), n))
    print("\n#### 抽样 60 条")
    for cid, fk, anchor, gov, tier, tid, word, place in rows:
        print("   %-10s %-8s %-11s gov=%-24s tier=%-7s tid=%-8s word=%-8s last_place=%s" % (
            cid, fk, anchor, gov or "-", tier, tid, word or "-", place or "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
