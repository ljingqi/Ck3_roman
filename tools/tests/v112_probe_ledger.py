# -*- coding: utf-8 -*-
"""v112 定稿清点：output/洪氏2 各篇成稿里六问旧形态的残留（决定是否重生成）。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_ledger.py
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "output", "洪氏2")
PATS = ["消失无踪", "其的", "、前代传主", "于当日", "凡例", "世系图"]


def main():
    names = sorted(n for n in os.listdir(OUT)
                   if n.endswith(".md") and not n.startswith("_"))
    print("%-44s %s" % ("篇名", "  ".join("%-6s" % p for p in PATS)))
    for n in names:
        t = io.open(os.path.join(OUT, n), encoding="utf-8").read()
        row = "  ".join("%-6d" % t.count(p) for p in PATS)
        print("%-44s %s" % (n, row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
