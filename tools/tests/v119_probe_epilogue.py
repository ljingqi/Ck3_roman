# -*- coding: utf-8 -*-
"""v119 probe: what a 终传 file offers a campaign-level 封档总评 — file inventory, the per-piece
`**总评：**` paragraph (the only authored summary inside a 终传), and the 世系 head lines whose label
carries no title.

Read-only: it prints and writes logs/v119_epilogue_<folder>.txt / .json only.

Usage:  python tools/tests/v119_probe_epilogue.py [家族文件夹] [--dump]
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

FOLDER = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "洪氏2"
DUMP = "--dump" in sys.argv
OUT = os.path.join(ROOT, "output", FOLDER)

FINAL_RE = re.compile(r"^(.+?)_终传_(.+)$")
TITLE_RE = re.compile(r"^# 《(.+?)》$", re.M)
# The 总纲 (intro) is every paragraph between the byline blockquote and the first `---`; it always
# closes with the piece's own 总评, whether or not the writer labels it `**总评：**`
INTRO_RE = re.compile(r"^> [^\n]*\n(.+?)\n---", re.M | re.S)
TOTAL_RE = re.compile(r"\*\*总评：\*\*\s*(.+?)(?=\n\s*\n|\n---|\Z)", re.S)
PIECE_RE = re.compile(r"^## \d+、《(.+?)》", re.M)


def main():
    files = sorted(f for f in os.listdir(OUT)
                   if f.endswith(".md") and FINAL_RE.match(f))
    print(f"== {FOLDER}：{len(files)} 篇终传 ==", flush=True)
    rows = []
    for name in files:
        text = open(os.path.join(OUT, name), encoding="utf-8").read()
        total = TOTAL_RE.search(text)
        intro = INTRO_RE.search(text)
        pieces = PIECE_RE.findall(text)
        title = TITLE_RE.search(text)
        rows.append({
            "file": name,
            "chars": len(text),
            "title": title.group(1) if title else "",
            "pieces": pieces,
            "intro": " ".join((intro.group(1) if intro else "").split()),
            "total": " ".join((total.group(1) if total else "").split()),
        })
        r = rows[-1]
        print(f"  {name:<44}{len(text):>7}字  篇={len(pieces):>2}"
              f"  总纲={len(r['intro']):>4}字  总评={'有' if r['total'] else '无'}", flush=True)
    joined = sum(len(r["intro"]) for r in rows)
    print(f"\n总纲合计 {joined} 字；终传正文合计 {sum(r['chars'] for r in rows)} 字")
    if DUMP:
        for r in rows:
            print(f"\n--- {r['file']}\n{r['intro']}")
    json.dump(rows, open(os.path.join(ROOT, "logs", f"v119_epilogue_{FOLDER}.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=1)
    txt = os.path.join(ROOT, "logs", f"v119_epilogue_{FOLDER}.txt")
    with open(txt, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(f"## {r['file']}\n篇目：{'、'.join(r['pieces'])}\n总纲：{r['intro']}\n\n")
    print("已写", txt)


if __name__ == "__main__":
    main()
