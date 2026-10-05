# -*- coding: utf-8 -*-
"""v104 probe: dump culture entries (271 Hiberno-Norse, 161 norse, 75 irish, 82 catalan) keys.

Usage: py tools/tests/v104_probe_culture_entry.py <melt> [cid ...]
"""
import json
import sys

from v104_probe_melt_activity import stream
from v104_probe_faiths import slice_value


def main():
    path = sys.argv[1]
    wants = sys.argv[2:] or ["271", "161", "75", "82"]
    needle = b'"culture_manager"'
    buf, blob = b"", None
    for chunk in stream(path):
        buf += chunk
        p = buf.find(needle)
        if p >= 0:
            j = buf.find(b"{", p)
            end = slice_value(buf, j)
            blob = buf[j:end]
            break
        buf = buf[-64:]
    if blob is None:
        print("culture_manager not found")
        return
    print("culture_manager bytes", len(blob))
    cm = json.loads(blob.decode("utf-8"))
    print("culture_manager keys", sorted(cm.keys()))
    tc = cm.get("template_cultures")
    print("template_cultures:", json.dumps(tc, ensure_ascii=False)[:2000])
    db = (cm.get("cultures") or {})
    print("cultures count", len(db))
    for cid in wants:
        e = db.get(cid)
        if not isinstance(e, dict):
            print("culture", cid, "absent; sample ids", sorted(db.keys())[:20])
            continue
        print("=" * 70)
        print("culture", cid, "keys", sorted(e.keys()))
        pick = {k: e.get(k) for k in ("name", "culture_template", "name_list",
                                      "name_order_convention", "parents", "heritage", "head",
                                      "prefix", "collective_noun", "language", "ethos",
                                      "created", "template")}
        print(json.dumps(pick, ensure_ascii=False)[:1200])


if __name__ == "__main__":
    main()
