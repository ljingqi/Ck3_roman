# -*- coding: utf-8 -*-
"""v98 成稿核对：三篇十年传（新稿 vs 备份）——署名、篇目、枢机团与教宗选举段落。

用法：& tools\\py.ps1 tools\\tests\\v98_check_articles.py
输出 logs/v98_check_articles.txt（UTF-8）+ 控制台摘要
"""
import glob
import os
import re

ROOT = r"D:\Roman"
FOLDER = os.path.join(ROOT, "output", "洪氏2")
OUT = os.path.join(ROOT, "logs", "v98_check_articles.txt")
LINES = []


def P(s=""):
    LINES.append(str(s))


def chapters(text):
    """→ [(标题, 正文)]，按二级标题切。"""
    out, cur, buf = [], None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur is not None:
                out.append((cur, "\n".join(buf)))
            cur, buf = line[3:].strip(), []
        else:
            buf.append(line)
    if cur is not None:
        out.append((cur, "\n".join(buf)))
    return out


def show(path, tag):
    text = open(path, encoding="utf-8").read()
    chs = chapters(text)
    P("=" * 78)
    P("### %s  %s  (%d 篇, %d 字)" % (tag, os.path.basename(path), len(chs), len(text)))
    head = [ln for ln in text.splitlines() if ln.startswith("<!--") or ln.startswith("# ")]
    for ln in head[:3]:
        P("  %s" % ln[:150])
    proto = [ln for ln in text.splitlines() if ln.startswith("> ")]
    for ln in proto[:1]:
        P("  %s" % ln[:150])
    P("  「尼各老」%d 处 / 「洪思忠」%d 处 / 「教宗」%d 处 / 「枢机」%d 处"
      % (text.count("尼各老"), text.count("洪思忠"), text.count("教宗"), text.count("枢机")))
    P("  「无地冒险者」%d 处 / 「营地」%d 处 / 「虚悬」%d 处"
      % (text.count("无地冒险者"), text.count("营地"), text.count("虚悬")))
    # 篇目
    P("  篇目: %s" % " / ".join(t for t, _b in chs))
    # 枢机团与教宗选举所在章节
    for title, body in chs:
        if "礼仪志" in title or "枢机" in body:
            paras = [p.strip() for p in body.split("\n") if p.strip()]
            hit = [p for p in paras if ("枢机" in p or "教宗" in p)]
            P("  --- %s（%d 段，含枢机/教宗 %d 段） ---" % (title, len(paras), len(hit)))
            for p in hit[:6]:
                P("      %s" % p[:400])
    P()


def main():
    # v98 重生成后的三篇（按当日名命名；d1/d2 是洪思忠，d3 是尼各老）
    NEW = ["洪思忠(917)_传记_第1个十年_963_01_01.md",
           "洪思忠(917)_传记_第2个十年_973_01_01.md",
           "尼各老(917)_传记_第3个十年_983_01_01.md"]
    new = [os.path.join(FOLDER, f) for f in NEW if os.path.isfile(os.path.join(FOLDER, f))]
    old = sorted(glob.glob(os.path.join(FOLDER, "_v98_before", "*917*_传记_*.md")))
    live = sorted(glob.glob(os.path.join(FOLDER, "_v97_before", "*917*_传记_*.md")))
    for p in new:
        show(p, "新稿")
    for p in old:
        show(p, "备份(984档旧稿)")
    for p in live:
        show(p, "当年原稿(实跑)")
    open(OUT, "w", encoding="utf-8").write("\n".join(LINES) + "\n")
    print("写出 %s（%d 行）" % (OUT, len(LINES)))
    for p in new:
        print("新稿: %s (%d 字节)" % (os.path.basename(p), os.path.getsize(p)))


if __name__ == "__main__":
    main()
