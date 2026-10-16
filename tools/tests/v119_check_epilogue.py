# -*- coding: utf-8 -*-
"""v119 check: the written 封档总评 covers every generation and every roster ruler, and the reading
page carries it.

Reads only the folder's Markdown/HTML (no melt), so it is a cheap post-run gate:
    python tools/tests/v119_check_epilogue.py [家族文件夹]
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import epilogue as E  # noqa: E402
import llm            # noqa: E402
import style          # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "洪氏2"
NEG = re.compile("不要|避免|禁止|切勿|不得|请勿")
# the model re-punctuates labels (，→、, ‑→-), so the comparison runs on bare characters
PUNCT = re.compile(r"[，、,·\-‑‐–—\s]")


def _bare(s):
    return PUNCT.sub("", s)


def main():
    cfg = llm.load_config()
    base = os.path.join(cfg["output_dir"], FOLDER)
    path, date = E.epilogue_file(base)
    fails = []

    def check(ok, label, extra=""):
        print(f"  {'PASS' if ok else 'FAIL'} {label}" + (f"  {extra}" if extra else ""))
        if not ok:
            fails.append(label)

    check(path is not None, "封档总评文件存在", os.path.basename(path or ""))
    if not path:
        return 1
    text = open(path, encoding="utf-8").read()
    ch = E.chapters(base)
    head = text.split("-->", 1)[0]
    part1 = text.split("## 一、历代总述", 1)[1].split("## 二、", 1)[0]
    part2 = text.split("## 二、当世同宗诸统治者", 1)[1].split("\n---\n", 1)[0]
    table = text.split("## 附：", 1)[1]

    check(bool(re.search(r"存档:\s*[\d.]+", head)), "header 存档日期非空", head[:60])
    check("None" not in text, "成稿无空值 None")
    check(text.count("## 二、当世同宗诸统治者") == 1, "第二部分标题只出现一次")
    check(text.count("## 一、历代总述") == 1, "第一部分标题只出现一次")
    check(len(part1) >= 1600, "第一部分篇幅达标", f"{len(part1)} 字")
    check(len(part2) >= 900, "第二部分篇幅达标", f"{len(part2)} 字")

    missing = [r["person"] for r in ch["rows"]
               if r["person"].split("·")[-1][-3:] not in part1 and r["person"] not in part1]
    check(not missing, "第一部分点到全部传主", f"缺 {missing}")
    check(part1.rstrip()[-1:] in "。！？…」", "第一部分收尾完整", part1.rstrip()[-12:])
    check(part2.rstrip()[-1:] in "。！？…」", "第二部分收尾完整", part2.rstrip()[-12:])

    # the main table is what part 2 was given; the 其余在世同宗 sub-list is appendix-only.
    # Each row reads 「<末代传主>的<亲属称谓><本人名号>，属<房支>，为人<…>。」and the label itself
    # may carry offices separated by 「，」, so the ruler's name is taken from the segment before
    # the 属/为人 clauses; the model re-punctuates everything, so the comparison bares punctuation
    # and matches the closing three characters of the name (the given name, as the 传主 check does).
    main_table = table.split("### 其余在世同宗", 1)[0]
    rows = [ln for ln in main_table.split("\n") if ln.startswith("- ")]

    def _row_name(ln):
        s = ln[2:].rstrip("。")
        for sep in ("，属", "，为人"):
            s = s.split(sep, 1)[0]
        return s.split("的")[-1][-3:]

    check(len(rows) >= 1, "附录名册非空", f"{len(rows)} 行")
    short = [n for n in (_row_name(r) for r in rows) if _bare(n) not in _bare(part2)]
    check(not short, "第二部分覆盖附录名册", f"缺 {short[:3]}")
    check("｜" not in table and all("为人" in r for r in rows), "名册为「…的…，为人…。」句式",
          rows[0][:60] if rows else "")

    page = os.path.join(base, "index.html")
    html = open(page, encoding="utf-8").read() if os.path.exists(page) else ""
    data = json.loads(html.split("const DATA = ", 1)[1].split(";\n", 1)[0]) if html else {}
    epi = (data.get("epilogue") or {})
    check(bool(epi.get("file")), "阅读页带封档总评", epi.get("file", ""))
    check("epi-btn" in html, "阅读页有封档总评按钮")

    prompt_text = "\n".join(style.PROMPTS[k] for k in
                            ("epilogue_system", "epilogue_part1_user", "epilogue_part2_user"))
    check(not NEG.search(prompt_text), "新提示词无负向措辞")

    print("\n" + ("全部通过" if not fails else f"未过 {len(fails)} 项: " + "、".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
