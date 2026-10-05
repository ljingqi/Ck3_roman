# -*- coding: utf-8 -*-
"""v104 probe: which container holds `puppets` in 135480's record (playable_data vs alive_data)?"""
import re
import sys

from v104_probe_melt_activity import stream
from v104_probe_faiths import slice_value


def main():
    path = sys.argv[1]
    cid = sys.argv[2].encode()
    needle = b'"' + cid + b'":{"first_name"'
    tail = b""
    rec = None
    for chunk in stream(path):
        data = tail + chunk
        p = data.find(needle)
        if p >= 0:
            start = p + len(cid) + 3
            nxt = re.search(rb'\},"(\d{4,12})":\{"first_name"', data[start:])
            end = start + (nxt.start() + 1 if nxt else 20000)
            rec = data[start:end]
            break
        tail = data[-len(needle) - 8:]
    if rec is None:
        print("character", cid, "not found")
        return
    print("record bytes", len(rec))
    for m in re.finditer(rb'"(playable_data|alive_data|dead_data|name)"\s*:\s*\{', rec):
        j = rec.find(b"{", m.end() - 1)
        end = slice_value(rec, j)
        body = rec[j:end]
        has = b'"puppets"' in body
        print("container", m.group(1).decode(), "at", m.start(), "bytes", len(body),
              "has puppets:", has)
        if has:
            q = body.find(b'"puppets"')
            print("   puppets ctx:", body[q:q + 200].decode("utf-8", "replace"))
    # also the raw position
    q = rec.find(b'"puppets"')
    print("raw puppets offset", q)
    if q >= 0:
        print(rec[max(0, q - 200):q + 160].decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
