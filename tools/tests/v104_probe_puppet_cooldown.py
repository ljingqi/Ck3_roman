# -*- coding: utf-8 -*-
"""v104 probe: character-interaction cooldown records between 135480 and 16884508."""
import sys

from v104_probe_melt_activity import stream

NEEDLES = [
    b'{"first":135480,"second":16884508',
    b'{"first":16884508,"second":135480',
    b'"make_clerical_puppet_interaction"',
    b'"make_external_clerical_puppet_interaction"',
]


def main():
    for path in sys.argv[1:]:
        print("=" * 70)
        print(path)
        counts = {n: 0 for n in NEEDLES}
        ctxs = {}
        tail = b""
        for chunk in stream(path):
            data = tail + chunk
            for n in NEEDLES:
                c = data.count(n)
                if c:
                    counts[n] += c
                    if n not in ctxs:
                        p = data.find(n)
                        ctxs[n] = data[max(0, p - 200):p + 500]
            tail = data[-96:]
        for n in NEEDLES:
            print("  ", n.decode()[:60], counts[n])
        for n, c in ctxs.items():
            print("--- ctx", n.decode()[:50])
            print(c.decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
