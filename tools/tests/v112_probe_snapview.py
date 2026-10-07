# -*- coding: utf-8 -*-
"""v112 只读检视：把新快照里六问的相关面直接打出来（不载熔件）。

用法: & tools\\py.ps1 tools\\tests\v112_probe_snapview.py [快照.json]
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT = os.path.join(ROOT, "output", "洪氏2", "data", "snap_v112_207044_final.json")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    with io.open(path, encoding="utf-8") as fp:
        snap = json.load(fp)
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    lines = []
    for k, v in blocks.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                lines.append((f"{k}/{kk}", vv or ""))
        else:
            lines.append((k, str(v)))
    text = "\n".join(t for _k, t in lines)

    print("== 1a 死者行（刺客列传）==")
    for k, t in lines:
        if not k.startswith("assassins"):
            continue
        for ln in t.splitlines():
            if ln.startswith("死者：") or ln.startswith("亲缘："):
                print("  " + ln)
    print("  重复亲缘词命中:", re.findall(r"(仇敌|同族兄弟|姻亲兄弟|族兄弟)(?:兼\1)", text)[:5])
    print("  「其的」命中:", text.count("其的"), " 「在其的命令下」:", text.count("在其的命令下"))

    print("\n== 1b 消失无踪 ==")
    print("  「消失无踪」:", text.count("消失无踪"), " 「消失得无影无踪」:", text.count("消失得无影无踪"))
    for ln in text.splitlines():
        if "消失" in ln:
            print("  " + ln.strip())

    print("\n== 2 亲缘行 ==")
    kin = [ln for k, t in lines for ln in t.splitlines() if ln.startswith("亲缘：")]
    print("  共 %d 行；含「年生」的行：%d" % (len(kin), sum("年生" in x for x in kin)))
    for ln in kin[:6]:
        print("  " + ln)

    print("\n== 3 承继句 ==")
    for ln in ((facts.get("protagonist") or {}).get("succession") or []):
        print("  " + ln)

    print("\n== 4 语言行 ==")
    p = facts.get("protagonist") or {}
    print("  传主: " + str(p.get("language_line")))
    n = 0
    for who, blk in (blocks or {}).items():
        for kk, vv in (blk.items() if isinstance(blk, dict) else []):
            for ln in str(vv or "").splitlines():
                if "母语" in ln:
                    n += 1
                    if n <= 8:
                        print("  [%s] %s" % (who, ln.strip()[:120]))
    print("  母语行共 %d" % n)

    print("\n== 5 双胞胎 ==")
    for m in re.finditer(r".{16}双胞胎.{6}", text):
        print("  …" + m.group(0) + "…")
    print("  裸「双胞胎」命中:", len(re.findall(r"(?<!为)双胞胎", text)))

    print("\n== 6 世系 ==")
    for ln in (facts.get("genealogy") or []):
        print("  | " + ln)
    print("  --- genealogy_subject ---")
    for ln in (facts.get("genealogy_subject") or []):
        print("  S " + ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
