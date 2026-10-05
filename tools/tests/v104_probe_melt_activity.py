# -*- coding: utf-8 -*-
"""v104 probe: look for activity / puppet traces in a melt by streaming byte scan.

Usage: py tools/tests/v104_probe_melt_activity.py <melt-path> [needle ...]
Handles plain .json and streamed .json.xz without ever json.loads-ing the whole file.
"""
import lzma
import sys
import zlib

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1077_01_01.json"
NEEDLES = [b'"activity_manager"', b'"activities"', b'"activity_type"', b'ecumenical_council',
           b'"puppeteer"', b'clerical_puppet', b'"active_activity"', b'"location"']


def stream(path, chunk=1 << 24):
    if path.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    return
                yield b
    else:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    return
                yield b


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    needles = [a.encode("utf-8") for a in sys.argv[2:]] or NEEDLES
    counts = {n: 0 for n in needles}
    first = {}
    tail = b""
    total = 0
    for chunk in stream(path):
        data = tail + chunk
        base = total - len(tail)
        for n in needles:
            p = 0
            while True:
                p = data.find(n, p)
                if p < 0:
                    break
                counts[n] += 1
                if n not in first:
                    first[n] = (base + p, data[max(0, p - 250):p + 400])
                p += 1
        total = base + len(data)
        tail = data[-64:]
    print("file", path, "decompressed bytes ~", total)
    for n in needles:
        print("=" * 70)
        print(n.decode(), "count", counts[n])
        if n in first:
            off, ctx = first[n]
            print("first at", off)
            print(ctx.decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
