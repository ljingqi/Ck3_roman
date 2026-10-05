# -*- coding: utf-8 -*-
"""v104 probe: find character-level `puppeteer` fields in a melt by streamed regex scan."""
import lzma
import re
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"
PAT = re.compile(rb'"puppeteer":(\d+)')


def stream(path, chunk=1 << 24):
    op = lzma.open if path.endswith(".xz") else open
    with op(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                return
            yield b


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    want = int(sys.argv[2]) if len(sys.argv) > 2 else None
    tail = b""
    total = 0
    hits = {}
    ctxs = []
    for chunk in stream(path):
        data = tail + chunk
        for m in PAT.finditer(data):
            v = int(m.group(1))
            hits[v] = hits.get(v, 0) + 1
            if want is not None and v == want and len(ctxs) < 5:
                s = max(0, m.start() - 700)
                ctxs.append((total - len(tail) + m.start(), data[s:m.end() + 200]))
        total += len(chunk)
        tail = data[-32:]
    print("file", path)
    print("character-level puppeteer fields:", sum(hits.values()), "distinct masters:", len(hits))
    for v, n in sorted(hits.items(), key=lambda kv: -kv[1])[:20]:
        print("   master", v, "puppets", n)
    for off, c in ctxs:
        print("-" * 60, off)
        print(c.decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
