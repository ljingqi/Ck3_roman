# -*- coding: utf-8 -*-
"""v104 probe: dump wide context around every `"puppets":[` in a melt (streamed)."""
import re
import sys

from v104_probe_melt_activity import stream  # reuse the streamer

PAT = re.compile(rb'"puppets"\s*:\s*\[')
WANT = re.compile(rb'"(\d{4,12})":\{"first_name"')


def main():
    path = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    back = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
    tail = b""
    shown = 0
    for chunk in stream(path):
        data = tail + chunk
        for m in PAT.finditer(data):
            s = max(0, m.start() - back)
            ctx = data[s:m.start()]
            ids = WANT.findall(ctx)
            print("=" * 70)
            print("context before `\"puppets\":[` (closest char ids:", [i.decode() for i in ids[-3:]],
                  ")")
            print(ctx[-1200:].decode("utf-8", "replace"))
            print(">>> PUPPETS", data[m.start():m.start() + 300].decode("utf-8", "replace"))
            shown += 1
            if shown >= limit:
                return
        tail = data[-back:]


if __name__ == "__main__":
    main()
