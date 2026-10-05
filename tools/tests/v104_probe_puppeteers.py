# -*- coding: utf-8 -*-
"""v104 probe: does a puppeteers variable (puppet side) name 135480 before the 1056 council?"""
import sys

from v104_probe_melt_activity import stream

NEEDLES = [
    b'"name":"puppeteers","item":{"type":"char","identity":135480}',
    b'"name":"puppeteers","item":{"type":"char","identity":16884508}',
    b'"puppets":[{"character":16884508',
    b'"puppets":[{"character"',
]


def main():
    for path in sys.argv[1:]:
        found = {n: 0 for n in NEEDLES}
        first = {}
        tail = b""
        for chunk in stream(path):
            data = tail + chunk
            for n in NEEDLES:
                c = data.count(n)
                if c:
                    found[n] += c
                    if n not in first:
                        p = data.find(n)
                        first[n] = data[max(0, p - 300):p + 120]
            tail = data[-96:]
        print("=" * 70)
        print(path)
        for n in NEEDLES:
            print("  ", n.decode()[:60], found[n])
        for n, ctx in first.items():
            if n.endswith(b'135480}'):
                print("   ctx", ctx.decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
