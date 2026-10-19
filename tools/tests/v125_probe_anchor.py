# -*- coding: utf-8 -*-
"""v125 探针五：确认「岳母兼儿媳」是相对杨过算出的，并查该句的关系缘由键与模板主语。"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402
import localization as L  # noqa: E402

FOLDER, PID, AS_OF = "杨氏", 38932, "912.10.6"


def main():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache = json.load(open(os.path.join(data, f"player_{PID}.json"), encoding="utf-8"))
    melts = [x for x in os.listdir(data)
             if x.startswith("melt_") and "_idx" not in x and x.endswith(".json")]

    def _k(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)
    melt = cl.load_melt(os.path.join(data, max(melts, key=_k)))
    facts = F.build_facts(cache, melt, os.path.join(data, "names.json"),
                          as_of=AS_OF, decade=None, campaign=None)
    f = facts["_facts"]
    out = []
    def p(*a):
        out.append(" ".join(str(x) for x in a))

    han, bai, guo = 43998, 44126, 38932
    p("identity_parts(韩吉娘, 杨过) =", f.identity_parts(han, guo))
    p("identity_parts(韩吉娘, 杨白劳) =", f.identity_parts(han, bai))
    p("chain(韩吉娘, 杨过) =", "兼".join(f.kin_chain_words_for(han, guo)))
    p("")
    for kinds in (("lover",), ("soulmate",)):
        for kk in f.relation_reason_for_pair(han, bai, kinds, styled=True, keys=True):
            p("reason", kinds, "=>", kk[0])
            p("   text:", kk[1])
            tpl = L.relation_templates().get(kk[0]) or ""
            p("   tpl :", tpl)
            m = re.search(r"\[(TARGET_CHARACTER_2|TARGET_CHARACTER|CHARACTER)[.\]]", tpl)
            p("   first role in tpl:", m.group(1) if m else None)
    txt = "\n".join(out)
    with open(os.path.join(ROOT, "logs", "v125_probe_e.txt"), "w", encoding="utf-8") as fp:
        fp.write(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())

