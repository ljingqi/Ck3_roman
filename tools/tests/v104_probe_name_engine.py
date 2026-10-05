# -*- coding: utf-8 -*-
"""v104 probe: how does the engine itself render a culture-255/259 character's name?

Searches the melt for the Chinese rendered-name strings the engine writes into descriptions, and
prints culture 255/259's naming fields, to decide whether the name-list template or the
paternal/house chain is the engine's authority for those hybrids.
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "tests"))
import cache_lib as cl            # noqa: E402
from v104_probe_melt_activity import stream   # noqa: E402

MELT = os.path.join(ROOT, "output", "洪氏2", "data", "melt_1077_01_01.json")
OUT = os.path.join(ROOT, "logs", "v104_name_engine.txt")
NEEDLES = ["厄德伍尔夫", "梅尔斯韦恩", "卡赫兰", "加尔比斯", "奥斯屈德尔", "季尔松"]


def main():
    lines = []

    def p(*a):
        s = " ".join(str(x) for x in a)
        lines.append(s)

    cm = cl.load_melt_section(MELT, "culture_manager") or {}
    cults = cm.get("cultures") or {}
    for cid in ("255", "259", "271"):
        e = cults.get(cid) or {}
        p("culture", cid, json.dumps({k: e.get(k) for k in
                                      ("name", "culture_template", "name_list", "parents",
                                       "language", "heritage", "name_order_convention")},
                                     ensure_ascii=False))
    table = cl._name_list_templates({"culture_manager": cm})
    for cid in ("255", "259", "271"):
        e = cults.get(cid) or {}
        nls = cl._as_name_list(e.get("name_list"))
        p("  →", cid, "name_list", nls, "resolves to", [(n, table.get(n)) for n in nls])

    # the engine's own rendered names: search the raw JSON text for the father names
    hits = {n: [] for n in NEEDLES}
    tail = b""
    for chunk in stream(MELT):
        data = tail + chunk
        for n in NEEDLES:
            if len(hits[n]) >= 4:
                continue
            b = n.encode("utf-8")
            pos = 0
            while len(hits[n]) < 4:
                i = data.find(b, pos)
                if i < 0:
                    break
                ctx = data[max(0, i - 120):i + 60]
                hits[n].append(ctx.decode("utf-8", "replace"))
                pos = i + 1
        tail = data[-256:]
    for n in NEEDLES:
        p("=" * 60, n, len(hits[n]))
        for c in hits[n]:
            p("   ", c.replace("\n", " ")[-170:])

    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:14]))
    print("full:", OUT)


if __name__ == "__main__":
    main()
