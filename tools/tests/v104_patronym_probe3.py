# -*- coding: utf-8 -*-
"""v104 probe 3: engine-rendered patronymic names frozen inside save strings.

Streams the melt as UTF-8 text (no json.loads) and harvests every
"<given>·<father><suffix>" style Chinese name, plus the culture-271 entry and
the 洪堡 house entry. Read-only.
"""
import io
import os
import re
import sys
from collections import Counter

MELT = r"D:\Roman\output\洪氏2\data\melt_1077_01_01.json"
OUT = r"D:\Roman\logs\v104_patronym_probe3.txt"
CHUNK = 8 * 1024 * 1024

out = io.StringIO()


def p(*a):
    print(*a, file=out)


CJK = r"\u4e00-\u9fff\u3400-\u4dbf"
NAME_PAIR = re.compile(rf"([{CJK}]{{1,6}})·([{CJK}\u00b7]{{1,8}})")
SUFFIXED = re.compile(rf"([{CJK}]{{1,6}})(松|森|斯多蒂尔|斯多特|多特|斯多赫托尔|多蒂尔)")


def stream_text():
    """Yield decoded text chunks with a small carry-over so names spanning a chunk survive."""
    dec = io.TextIOWrapper(open(MELT, "rb"), encoding="utf-8", errors="replace")
    carry = ""
    while True:
        buf = dec.read(CHUNK)
        if not buf:
            break
        yield carry + buf
        carry = buf[-40:]
    if carry:
        yield carry


def main():
    pairs = Counter()
    suffixed = Counter()
    yaoguo_ctx = []
    for text in stream_text():
        for m in NAME_PAIR.finditer(text):
            pairs[m.group(0)] += 1
        for m in SUFFIXED.finditer(text):
            suffixed[m.group(0)] += 1
        s = 0
        while True:
            i = text.find("耀国", s)
            if i < 0:
                break
            yaoguo_ctx.append(text[max(0, i - 60):i + 40].replace("\n", " "))
            s = i + 1

    p("=== A) names ending in a norse/patronymic suffix (rendered text in save) ===")
    for n, c in suffixed.most_common(120):
        p(f"  {n}  x{c}")

    p()
    p("=== B) dotted name pairs containing a patronymic suffix ===")
    seen = 0
    for n, c in pairs.most_common():
        if re.search(r"(松|森|斯多蒂尔|斯多特|多特|麦克|妮克)$", n.split("·")[-1]):
            p(f"  {n}  x{c}")
            seen += 1
            if seen > 150:
                break

    p()
    p("=== C) every occurrence of 耀国 in the melt text ===")
    for c in yaoguo_ctx:
        p("  " + c)

    p()
    p("=== D) culture 271 entry (anchored on the literal name) ===")
    p("")
    return 0


if __name__ == "__main__":
    main()
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(out.getvalue())
    sys.stderr.write(f"written {OUT}\n")
