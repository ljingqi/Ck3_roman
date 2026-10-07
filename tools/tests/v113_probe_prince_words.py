# -*- coding: utf-8 -*-
"""v113 probe: every realm-word + prince/princess word in three snapshots (no melt).

Watches the v113 change (a parent's realm word follows his own tenure) for side effects on the
male/female imperial-child words and the 大 prefix."""
import collections
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
FILES = ["snap_v112_207044_final.json", "snap_v113_207044_final.json"]
NAMES = ["李星雁", "洪天姣", "洪天贵福", "李漼", "洪秀全"]
TOKEN = re.compile(r"[唐天邓隋宋大汉]{0,2}(?:皇|公|王)(?:女|子|后|帝)")


def main():
    for fn in FILES:
        p = os.path.join(ROOT, "output", "洪氏2", "data", fn)
        if not os.path.exists(p):
            print(f"{fn}: 缺")
            continue
        snap = json.load(io.open(p, encoding="utf-8"))
        blob = json.dumps(snap.get("facts") or {}, ensure_ascii=False)
        c = collections.Counter(TOKEN.findall(blob))
        print(f"\n{fn}  共 {len(blob)} 字")
        for w, n in c.most_common(14):
            print(f"    {w}: {n}")
        for who in NAMES:
            hits = collections.Counter(m.group(1) for m in
                                       re.finditer(r"([\u4e00-\u9fff·]{2,10}" + who + ")", blob))
            print(f"    {who}: " + "、".join(f"{k}×{v}" for k, v in hits.most_common(3)))


if __name__ == "__main__":
    main()
