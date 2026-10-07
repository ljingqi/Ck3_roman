# -*- coding: utf-8 -*-
"""v111 同类问题普查：把「名字来源」与「身份词来源」里的可疑族类一次数清。

只读最后一份熔件 + 本地化表，不载缓存。三类普查：

A. 身份词源 `dead_data.flavor`：所有下划线不足 3 段的键（`_dead_flavor_consistent` 对它们
   一律 return True，见 facts.py:2960-2962），看哪些是「裸档位词」（无政体段、无地点）。
B. 头衔名源 `title_name_data`：
   - `title_history_names` 里出现的键族（cn_* / *_collective_noun / dynn_title_* / 其它），
     其它族逐个列出，用来判断还有哪些「非地名伪影」被当成真实改名；
   - `specific_title_name` 与 `name` 不同、且该动态名恰是同一头衔名下某个族名的本地化文本
     （即 people-name 伪影）的头衔数。
C. `specific_map_name` / `specific_title_name` / `name` 三者关系计数。

用法：
    & tools\\py.ps1 tools\\tests\\v111_scan_name_sources.py <家族>
"""
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl            # noqa: E402
import localization as L          # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    data = os.path.join(ROOT, "output", sys.argv[1], "data")
    melts = sorted((x for x in os.listdir(data) if x.startswith("melt_")), key=lambda s: s)
    path = os.path.join(data, melts[-1])
    print("熔件 %s" % melts[-1], flush=True)
    melt = cl.load_melt(path)
    table = L.table()

    # ---------- A ----------
    chars = cl.all_characters(melt)
    short = collections.Counter()
    for cid, c in chars.items():
        if not isinstance(c, dict):
            continue
        fk = ((c.get("dead_data") or {}).get("flavor") or "")
        if fk and len(str(fk).split("_")) < 3:
            short[str(fk)] += 1
    print("\n#### A 身份词：下划线不足 3 段的 flavor 键（%d 种 / %d 人）"
          % (len(short), sum(short.values())))
    for k, n in short.most_common():
        print("   %-28s %6d  loc=%s" % (k, n, L.loc(table, k)))

    # ---------- B ----------
    lt = ((melt.get("landed_titles") or {}).get("landed_titles") or {})
    fam = collections.Counter()
    others = collections.Counter()
    n_diff = n_people = n_hist = n_custom = 0
    people_tools = collections.Counter()
    for tid, t in lt.items():
        if not isinstance(t, dict):
            continue
        tnd = t.get("title_name_data") or {}
        if (tnd.get("custom") or "").strip():
            n_custom += 1
        hist = tnd.get("title_history_names") or []
        people_texts = set()
        for h in hist:
            key = str((h or {}).get("name") or "")
            if not key:
                continue
            if key.endswith("_collective_noun"):
                fam["*_collective_noun"] += 1
                people_texts.add((L.loc(table, key) or "").strip())
            elif key.startswith("cn_"):
                fam["cn_*"] += 1
            elif key.startswith("dynn_title_"):
                fam["dynn_title_*"] += 1
            elif key.startswith("dynn_"):
                fam["dynn_*"] += 1
            else:
                fam["其它"] += 1
                others[key] += 1
        nm = (tnd.get("name") or "").strip()
        sp = (tnd.get("specific_title_name") or "").strip()
        sm = (tnd.get("specific_map_name") or "").strip()
        if sp and nm and sp != nm:
            n_diff += 1
            if hist:
                n_hist += 1
            if sp in people_texts:
                n_people += 1
                people_tools[sm == sp] += 1
    print("\n#### B 头衔名：title_history_names 键族 %s" % dict(fam))
    print("   其它族出现最多的 12 个键：%s" % others.most_common(12))
    print("   custom 非空 %d 个；specific≠name 的 %d 个（带 history 的 %d 个）" % (
        n_custom, n_diff, n_hist))
    print("   其中「动态名 = 同一头衔名下 *_collective_noun 的本地化文本」的 %d 个"
          "（specific_map_name 也等于该文本的：%s）" % (n_people, dict(people_tools)))

    # ---------- C ----------
    c = collections.Counter()
    for tid, t in lt.items():
        if not isinstance(t, dict):
            continue
        tnd = t.get("title_name_data") or {}
        nm = (tnd.get("name") or "").strip()
        sp = (tnd.get("specific_title_name") or "").strip()
        sm = (tnd.get("specific_map_name") or "").strip()
        c[(bool(nm), sp == nm, sm == nm, bool(sm))] += 1
    print("\n#### C (有name, specific==name, map==name, 有map) -> 计数")
    for k, n in c.most_common(10):
        print("   %s -> %d" % (k, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
