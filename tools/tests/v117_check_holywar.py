# -*- coding: utf-8 -*-
"""v117 check (item 2): a holy-war conquest must read as the game's own title history does.

Target wording (user decision, 2026-10-09): 从他的对手、{宗教}{礼仪}统治者{对方}处圣战征服{头衔}
-- e.g. 「从…伊斯兰教逊尼派统治者贾林谢赫大卫·设拉子－法尔斯处圣战征服部刻拉里翁王」.

Runs the production snapshot path (`facts.build_facts`) on 洪希晏's own volume (player 50565938,
melt_1245_01_01.json.xz, as_of 1247.1.1), whose melt holds the 1205.1.10 holy war for
d_bucellaria / c_hadrianopolis, and asserts on the rendered text.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_holywar.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl       # noqa: E402
import facts as F            # noqa: E402

FOLDER = "洪氏2"
PID = 50565938
MELT = "melt_1245_01_01.json.xz"
AS_OF = "1247.1.1"
LOG = os.path.join(ROOT, "logs", "v117_check_holywar.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def main():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache = json.load(open(os.path.join(data, f"player_{PID}.json"), encoding="utf-8"))
    melt = cl.load_melt(os.path.join(data, MELT))
    names = os.path.join(data, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    campaign = {}
    for fn in os.listdir(data):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        try:
            c = json.load(open(os.path.join(data, fn), encoding="utf-8"))
        except Exception:
            continue
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(m.group(1))] = c
    facts = F.build_facts(cache, melt, names, as_of=AS_OF, decade=None,
                          campaign=campaign or None)
    th = (facts.get("protagonist") or {}).get("titles_held") or ""
    blob = json.dumps(facts, ensure_ascii=False, default=lambda o: None)

    w(f"[{MELT} as_of={AS_OF}] titles_held:")
    for part in th.split("；"):
        if part.strip():
            w(f"    {part.strip()}")

    w("\n  lines mentioning 圣战 / 部刻拉里翁 anywhere in the facts:")
    seen = set()
    for m in re.finditer(r"[^；。\n]{0,80}(?:圣战|部刻拉里翁)[^；。\n]{0,80}", blob):
        s = m.group(0).replace("\\n", " ").strip()
        if s not in seen:
            seen.add(s)
            w(f"    · {s}")

    holy = [p for p in th.split("；") if "圣战征服" in p]
    checks = [
        ("[1] 历任行用「圣战征服」", bool(holy), holy[:1]),
        ("[2] 圣战行写出对方宗教＋礼仪统治者",
         any("统治者" in p and "从" in p for p in holy),
         [p for p in holy if "统治者" in p][:1]),
        ("[3] 不再出现「攻取部刻拉里翁」", "攻取部刻拉里翁" not in blob, ""),
        ("[4] 历代记不再写「借圣战夺取」", "借圣战夺取" not in blob, ""),
        ("[5] 圣战行仍点出对方姓名",
         any("贾林" in p for p in holy), [p for p in holy if "贾林" in p][:1]),
    ]
    ok = True
    w("")
    for name, cond, detail in checks:
        w(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"  | {detail}" if detail else ""))
        ok = ok and cond
    w(f"\n[{'PASS' if ok else 'FAIL'}] v117 ② holy-war wording check")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
