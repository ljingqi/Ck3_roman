# -*- coding: utf-8 -*-
"""v104 probe: check the three new latches in the rebuilt 洪氏2 cache (list or dict shaped)."""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "output", "洪氏2", "data", "player_135480.json")
OUT = os.path.join(ROOT, "logs", "v104_latch_check.txt")
KEYS = ("faith_tenets_history", "puppet_history", "council_history")


def slice_value(data, start):
    depth, i, in_str, esc = 0, start, False, False
    while i < len(data):
        ch = data[i:i + 1]
        if in_str:
            if esc:
                esc = False
            elif ch == b"\\":
                esc = True
            elif ch == b'"':
                in_str = False
        else:
            if ch == b'"':
                in_str = True
            elif ch in (b"{", b"["):
                depth += 1
            elif ch in (b"}", b"]"):
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return len(data)


def main():
    data = io.open(CACHE, "rb").read()
    out = ["cache bytes %d" % len(data)]
    for key in KEYS:
        needle = ('"%s":' % key).encode()
        i = data.find(needle)
        if i < 0:
            out.append("%s MISSING" % key)
            continue
        j = i + len(needle)
        while data[j:j + 1] in (b" ", b"\n"):
            j += 1
        end = slice_value(data, j)
        blk = json.loads(data[j:end].decode("utf-8"))
        if isinstance(blk, dict):
            out.append("%s dict ids=%s rows=%s" % (key, sorted(blk.keys())[:4],
                                                   {k: len(v) for k, v in blk.items()}))
            rows = list(blk.values())[0]
        else:
            rows = blk
            out.append("%s list rows=%d" % (key, len(blk)))
        for e in rows[:2] + rows[-2:]:
            s = json.dumps(e, ensure_ascii=False)
            out.append("    " + (s[:220] + ("…" if len(s) > 220 else "")))
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
