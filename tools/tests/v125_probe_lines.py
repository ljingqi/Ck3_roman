# -*- coding: utf-8 -*-
"""v125 探针二：定位「惟仁亲王」「岳母兼儿媳」两条事实句的 cid 与 registry。

只读。用法：& tools\\py.ps1 tools\\tests\\probe_v125b.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

FOLDER, PID = "杨氏", 38932
SNAP = os.path.join(ROOT, "output", FOLDER, "data", f"snap_{PID}_final.json")


def main():
    snap = json.load(open(SNAP, encoding="utf-8"))
    out = []

    def p(*a):
        out.append(" ".join(str(x) for x in a))

    ni = snap.get("name_index") or {}
    lo = snap.get("line_owner") or {}
    ls = snap.get("line_stated") or {}
    for line, pairs in ni.items():
        if "惟仁" in line or "韩吉娘" in line and "勾引" in line:
            p("LINE:", line[:120])
            p("  pairs:", pairs)
            p("  owner:", lo.get(line), " stated:", ls.get(line))

    # 家室档案·善良者杨白劳 的原句
    blk = (snap.get("blocks") or {}).get("jiashi_kid3") or {}
    txt = blk.get("家室档案·善良者杨白劳") or ""
    p("")
    p("== 家室档案原文（含岳母句） ==")
    for ln in txt.split("\n"):
        if "勾引" in ln or "成婚" in ln or "同房" in ln:
            p("  ", ln)

    # facts 侧 events
    char = (snap.get("characters") or {}).get("44126") or {}
    p("")
    p("== 44126 杨白劳 events ==")
    for e in (char.get("events") or []):
        if "勾引" in e or "成婚" in e:
            p("  events:", e)
    for e in (char.get("events_subjectless") or []):
        if "勾引" in e or "成婚" in e:
            p("  subjless:", e)
            p("    owner:", lo.get(e), " stated:", ls.get(e))
            p("    name_index:", ni.get(e))

    # 找惟仁：从 name_index 的 cid 看
    ids = set()
    for line, pairs in ni.items():
        if "惟仁" in line:
            for cid, lb in pairs:
                ids.add((int(cid), lb))
    p("")
    p("== 惟仁 cid 候选 ==", sorted(ids))
    p("")
    print("\n".join(out))
    with open(os.path.join(ROOT, "logs", "v125_probe_b.txt"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
