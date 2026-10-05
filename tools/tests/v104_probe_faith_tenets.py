# -*- coding: utf-8 -*-
"""v104 probe: faith 13 mainline rite + its tenets across melts (issue 1/2 evidence).

Usage: py tools/tests/v104_probe_faith_tenets.py <melt> [<melt> ...]
"""
import json
import sys

from v104_probe_melt_activity import stream
from v104_probe_faiths import slice_value


def load_container(data, needle):
    p = data.find(needle)
    if p < 0:
        return None
    j = data.find(b"{", p + len(needle) - 1)
    end = slice_value(data, j)
    return json.loads(data[j:end].decode("utf-8"))


def main():
    for path in sys.argv[1:]:
        buf = b""
        faiths = None
        for chunk in stream(path):
            buf += chunk
            if b'"faiths":{"database"' in buf:
                faiths = load_container(buf, b'"faiths":{"database"')
                break
            buf = buf[-64:]
        print("=" * 78)
        print(path, "faiths.database bytes", len(buf) if faiths is None else "ok")
        if not faiths:
            continue
        f13 = faiths.get("13") or {}
        mr = f13.get("main_rite")
        print("faith 13 main_rite", mr, "religious_head", f13.get("religious_head"),
              "doctrine", f13.get("doctrine"))
        tp = f13.get("tenet_popularity") or []
        if tp:
            print("   tenet_popularity top5",
                  sorted(tp, key=lambda d: -(d.get("score") or 0))[:5])
        # now the rites container
        buf2, rites = b"", None
        for chunk in stream(path):
            buf2 += chunk
            if b'"rites":{"database"' in buf2:
                rites = load_container(buf2, b'"rites":{"database"')
                break
            buf2 = buf2[-64:]
        if not rites:
            print("   rites not found")
            continue
        for rid in {str(mr), "154", "185"} - {"None"}:
            r = rites.get(rid)
            if not isinstance(r, dict):
                continue
            d = r.get("data") or {}
            ten = {}
            for e in (d.get("tenets") or []):
                if isinstance(e, dict) and e.get("tenet"):
                    ten.setdefault(str(e.get("status")), []).append(str(e["tenet"]))
            core = sorted(ten.get("core") or [])
            print("   rite", rid, "faith", r.get("faith"), "head_of_rite", r.get("head_of_rite"),
                  "name", d.get("name"), "core", core,
                  "counts", {k: len(v) for k, v in ten.items()})


if __name__ == "__main__":
    main()
