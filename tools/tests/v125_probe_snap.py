# -*- coding: utf-8 -*-
"""v125 探针三：用已落盘的 facts 快照定位两条句子的 cid 与 registry（不需要熔件）。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAP = os.path.join(ROOT, "output", "杨氏", "data", "snap_38932_final.json")


def main():
    snap = json.load(open(SNAP, encoding="utf-8"))
    f = snap["facts"]
    ni = f.get("name_index") or {}
    lo = f.get("line_owner") or {}
    ls = f.get("line_stated") or {}
    out = []

    def p(*a):
        out.append(" ".join(str(x) for x in a))

    p("== name_index / line_owner 命中 ==")
    for line, pairs in ni.items():
        if "惟仁" in line or ("韩吉娘" in line and "勾引" in line):
            p("LINE:", line[:150])
            p("  pairs:", pairs)
            p("  owner:", lo.get(line), " stated:", ls.get(line))

    p("")
    p("== 家室档案·杨白劳（blocks）==")
    for k, blk in (snap.get("blocks") or {}).items():
        for bk, bv in (blk or {}).items():
            if isinstance(bv, str) and "勾引" in bv and "韩吉娘" in bv:
                p(f"[{k} / {bk}]")
                for ln in bv.split("\n"):
                    if "韩吉娘" in ln:
                        p("   ", ln[:200])

    p("")
    p("== facts.characters[44126] ==")
    ch = (f.get("characters") or {}).get("44126") or {}
    p("keys:", list(ch.keys())[:30])
    for e in (ch.get("events") or []):
        if "韩吉娘" in e:
            p("  events:", e[:160], "| owner:", lo.get(e))
    for e in (ch.get("events_subjectless") or []):
        if "韩吉娘" in e:
            p("  subjless:", e[:160], "| owner:", lo.get(e),
              "| stated:", ls.get(e), "| index:", ni.get(e))

    p("")
    p("== 惟仁 cid ==")
    ids = sorted({int(cid) for line, pairs in ni.items() if "惟仁" in line
                  for cid, _lb in pairs})
    p("candidates:", ids)
    for cid in ids:
        rec = (f.get("characters") or {}).get(str(cid)) or {}
        p("  ", cid, rec.get("name"), rec.get("name_zh"), rec.get("label"),
          json.dumps(rec.get("death"), ensure_ascii=False))

    print("\n".join(out))
    with open(os.path.join(ROOT, "logs", "v125_probe_c.txt"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
