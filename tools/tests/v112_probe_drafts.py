# -*- coding: utf-8 -*-
"""v112 终稿检视：在两篇重生成的终传 md 上核对六问的成稿面（不载熔件）。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_drafts.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRAFTS = [
    "洪七公(1109)_终传_1152_11_13.md",
    "洪易卜拉欣(1059)_终传_1126_07_30.md",
]


def main():
    for name in DRAFTS:
        p = os.path.join(ROOT, "output", "洪氏2", name)
        old = os.path.join(ROOT, "output", "洪氏2", "_v112_before", name)
        t = io.open(p, encoding="utf-8").read()
        o = io.open(old, encoding="utf-8").read() if os.path.exists(old) else ""
        print("=" * 70)
        print("%s  新 %d 字 / 旧 %d 字" % (name, len(t), len(o)))
        for pat in ("消失无踪", "其的", "双胞胎", "凡例", "世系图", "五世为一图"):
            print("   %-8s 新 x%-3d 旧 x%d" % (pat, t.count(pat), o.count(pat)))
        heads = re.findall(r"^- \*\*([一二三四五六七八九十]+世)\*\*　[^\n]*", t, re.M)
        print("   世次行:", " ".join(heads))
        for m in re.finditer(r"^- \*\*[一二三四五六七八九十]+世\*\*　[^\n]*", t, re.M):
            print("     " + m.group(0)[:120])
        for m in re.finditer(r"[^\n]{0,24}(与[^\n，。；]{1,14}为双胞胎)[^\n]{0,16}", t):
            print("   双胞胎:", m.group(1))
        for m in re.finditer(r"^- \*\*[^\n]*\|", t):
            pass
        hits = [ln for ln in t.splitlines() if "消失" in ln]
        for ln in hits[:3]:
            print("   消失:", ln.strip()[:130])
    return 0


if __name__ == "__main__":
    sys.exit(main())
