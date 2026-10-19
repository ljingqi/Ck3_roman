# -*- coding: utf-8 -*-
"""v125 探针五：第三问「岳母兼儿媳」的行主语与按日取词（B 口径）。只读。

用法：& tools\\py.ps1 tools\\tests\\v125_probe_subject.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402
import biography as B    # noqa: E402

FOLDER, PID, AS_OF = "杨氏", 38932, "912.10.6"
HAN, YANG = 43998, 44126          # 韩吉娘 / 大和国王善良者杨白劳


def main():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache = json.load(open(os.path.join(data, f"player_{PID}.json"), encoding="utf-8"))
    melts = [x for x in os.listdir(data)
             if x.startswith("melt_") and "_idx" not in x and x.endswith(".json")]

    def _k(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)
    melt = cl.load_melt(os.path.join(data, max(melts, key=_k)))
    campaign = {}
    for fn in os.listdir(data):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        c = json.load(open(os.path.join(data, fn), encoding="utf-8"))
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(m.group(1))] = c
    facts = F.build_facts(cache, melt, os.path.join(data, "names.json"),
                          as_of=AS_OF, decade=None, campaign=campaign or None)
    f = facts["_facts"]
    out = []

    def p(*a):
        out.append(" ".join(str(x) for x in a))

    p("== ③ 韩吉娘/杨白劳 那一条记忆句 ==")
    rows = [(t, o, (facts.get("line_date") or {}).get(t))
            for t, o in (facts.get("line_owner") or {}).items() if "韩吉娘" in t]
    for t, o, d in rows:
        p(" 句:", t)
        p("   line_owner:", o, " line_date:", d)
    p(" identity(韩吉娘, 杨白劳) 无日:", f.identity_parts(HAN, YANG))
    p(" identity(韩吉娘, 杨白劳) @895.11.6:",
      f.identity_parts(HAN, YANG, date="895.11.6"))
    p(" identity(韩吉娘, 杨过) 无日:", f.identity_parts(HAN, PID))
    p(" relation_word_for(韩吉娘, 杨白劳):", f.relation_word_for(HAN, YANG) or "")
    p(" relation_word_for(韩吉娘, 杨白劳, 895.11.6):",
      f.relation_word_for(HAN, YANG, date="895.11.6") or "")
    p(" _rel_mem_date(soulmate):",
      f._rel_mem_date(HAN, f._REL_REASON_KINDS.get("soulmate"), base=YANG))
    p("")
    p("== 该句按 895 的口径渲染（行主语=杨白劳 与 退化口径=持有人）==")
    for t, o, d in rows:
        if "勾引" not in t:
            continue
        sc = F.KinScope(subject=YANG)
        p(" scope=杨白劳 :", B._kin_tag_line(facts, sc, t))
        sc2 = F.KinScope(subject=YANG)
        facts2 = dict(facts)
        facts2["line_owner"] = {t: HAN}
        facts2["line_date"] = {}
        p(" 退化(旧口径):", B._kin_tag_line(facts2, sc2, t))
    txt = "\n".join(out)
    with open(os.path.join(ROOT, "logs", "v125_probe_subject.txt"), "w",
              encoding="utf-8") as fp:
        fp.write(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
