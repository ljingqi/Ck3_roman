# -*- coding: utf-8 -*-
"""v123: walk a facts snapshot and print every string holding a marker (no melt load).

Usage:  python tools/tests/v123_probe_snapmark.py <snapshot.json> <marker> [<marker> ...]
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

SNAP = sys.argv[1]
MARKERS = sys.argv[2:]
if not os.path.isabs(SNAP):
    SNAP = os.path.join(ROOT, SNAP)


def walk(node, path, out):
    if isinstance(node, dict):
        for k, v in node.items():
            walk(v, path + "/" + str(k), out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, path + "/%d" % i, out)
    elif isinstance(node, str):
        for m in MARKERS:
            if m in node:
                out.append("%s\n    %s" % (path, node[:400].replace("\n", "⏎")))
                break


with io.open(SNAP, encoding="utf-8") as fp:
    data = json.load(fp)
out = []
walk(data, "", out)
print("命中 %d 处" % len(out))
print("\n".join(out[:60]))
