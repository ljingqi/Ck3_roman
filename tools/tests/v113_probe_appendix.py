# -*- coding: utf-8 -*-
"""v113 probe: shape of every 终传 appendix (no melt): where 世系 ends, what else lives in it."""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
D = os.path.join(ROOT, "output", "洪氏2")
GEN_HEAD = re.compile(r"^- \*\*[一二三四五六七八九十]+世\*\*　")
ROW_HEAD = re.compile(r"^- 　[^：]*：")
META = re.compile(r"^- (凡例：|世系图：|〈)")


def main():
    for fn in sorted(os.listdir(D)):
        if not fn.endswith(".md") or "终传" not in fn:
            continue
        text = io.open(os.path.join(D, fn), encoding="utf-8").read()
        m = re.search(r"^### 世系$", text, re.M)
        t = re.search(r"^### 大事年表$", text, re.M)
        if not m:
            print(f"{fn}: 无 ### 世系")
            continue
        block = text[m.start(): (t.start() if t else len(text))].splitlines()
        heads = [ln for ln in block if GEN_HEAD.match(ln)]
        rows = [ln for ln in block if ROW_HEAD.match(ln)]
        other = [ln for ln in block
                 if ln.startswith("- ") and not GEN_HEAD.match(ln) and not ROW_HEAD.match(ln)
                 and not META.match(ln)]
        print("=" * 72)
        print(f"{fn}  附录起始行 {text[:m.start()].count(chr(10)) + 1}  世系块 {len(block)} 行 "
              f"| 世次行 {len(heads)} | 亲属行 {len(rows)} | 其它行 {len(other)}")
        for ln in other[:6]:
            print("   其它:", ln[:160])


if __name__ == "__main__":
    main()
