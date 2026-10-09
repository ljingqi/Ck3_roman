# -*- coding: utf-8 -*-
"""v119 probe: prompt assembly of the 封档总评 — slot filling and input sizes, without a melt.

Reads only the campaign's 终传 files, so it is a cheap gate before the heavy run:
    python tools/tests/v119_probe_prompt.py [家族文件夹]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import epilogue as E  # noqa: E402
import llm            # noqa: E402
import style          # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "洪氏2"


def main():
    cfg = llm.load_config()
    base = os.path.join(cfg["output_dir"], FOLDER)
    ch = E.chapters(base)
    print(f"{FOLDER}: {len(ch['rows'])} 篇终传, 首章合计 {ch['chars']} 字")
    for r in ch["rows"][:3] + ch["rows"][-2:]:
        print(f"   {r['reign']:>10}  {r['person']:<16}{len(r['first']):>5}字  《{r['first_title']}》")
    # a stub roster: only the slots matter here
    rep = {"as_of": "1289.1.1", "dynasty_name": "洪", "house": 1, "house_label": "洪氏",
           "rows": [{"label": "某王", "title": "某王国", "seat": "某城", "house": "洪氏",
                     "kin": "族人", "independent": True, "rank": 4}],
           "others": [], "alive": 1,
           "protagonist": {"cid": 1, "name": "洪非帝", "house": "洪氏"}}
    rep["rows"][0]["rank"] = 4
    rule = style.rule_block("east")
    m1 = E.part1_messages(ch, rep, FOLDER, rule)
    m2 = E.part2_messages(ch, rep, FOLDER, rule)
    print(f"\npart1 system {len(m1[0]['content'])} 字 / user {len(m1[1]['content'])} 字")
    print(f"part2 system {len(m2[0]['content'])} 字 / user {len(m2[1]['content'])} 字")
    print("system 两段一致:", m1[0]["content"] == m2[0]["content"])
    print("part2 名册块:", [ln for ln in m2[1]["content"].split("\n") if ln.startswith("- ")])
    print("\n--- part1 user 头 ---")
    print("\n".join(m1[1]["content"].split("\n")[:8]))
    print("\n--- part2 user 尾 ---")
    print("\n".join(m2[1]["content"].split("\n")[-6:]))
    md = E.assemble(FOLDER, ch, rep, "（第一部分示例）", "（第二部分示例）", 167809330)
    print("\n--- 成稿骨架 ---")
    for ln in md.split("\n"):
        if ln.startswith(("#", ">", "<!--", "## 一", "## 二")):
            print("   ", ln[:90])
    print("output name:", E.output_name(FOLDER, "1289.1.1"))


if __name__ == "__main__":
    main()
