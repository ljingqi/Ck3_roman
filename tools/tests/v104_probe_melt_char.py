# -*- coding: utf-8 -*-
"""v104 probe: pull one character record out of a melt by streamed byte scan.

Usage: py tools/tests/v104_probe_melt_char.py <melt> <char-id> [field ...]
Prints the record slice (bounded) and any `puppets` / `known_tenets` it carries; with no field
list it prints the raw slice head. Also tallies every `puppet` type in the file when asked with
`--tally`.
"""
import json
import re
import sys

from v104_probe_melt_activity import stream
from v104_probe_faiths import slice_value

PUPPET = re.compile(rb'\{"character":(\d+),"type":"([a-z_]+)"\}')


def main():
    path = sys.argv[1]
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    cid = args[0] if args else None
    tally = "--tally" in sys.argv
    tail = b""
    rec = None
    cur = b""
    if tally:
        tally_map = {}
        for chunk in stream(path):
            data = tail + chunk
            for m in PUPPET.finditer(data):
                t = m.group(2).decode()
                tally_map[t] = tally_map.get(t, 0) + 1
            tail = data[-64:]
        print("puppet types:", tally_map)
        if cid is None:
            return
    needle = ('"%s":{"first_name"' % cid).encode()
    for chunk in stream(path):
        data = tail + chunk
        p = data.find(needle)
        if p >= 0:
            start = p + len(cid) + 3
            # find the end of this record: next `,"<id>":{"first_name"`
            nxt = re.search(rb'\},"(\d{4,12})":\{"first_name"', data[start:])
            end = start + (nxt.start() + 1 if nxt else 20000)
            rec = data[start:end]
            break
        tail = data[-len(needle) - 8:]
    if rec is None:
        print("character", cid, "not found")
        return
    print("record bytes", len(rec))
    head = rec[:1200].decode("utf-8", "replace")
    print("HEAD:", head)
    for key in ("puppets", "known_tenets", "family_data", "landed_data", "court_data",
                "trait_history", "alive_data", "dead_data", "name"):
        mm = re.search(('"%s":' % key).encode(), rec)
        if mm:
            if key == "puppets":
                j = rec.find(b"[", mm.end())
                end = slice_value(rec, j) if j >= 0 else mm.end() + 400
                print("FIELD", key, rec[mm.start():end].decode("utf-8", "replace"))
                continue
            nxt = re.search(rb'[,}]\s*"', rec[mm.end():])
            end = mm.end() + (nxt.start() + 1 if nxt else 400)
            print("FIELD", key, rec[mm.start():end][:800].decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
