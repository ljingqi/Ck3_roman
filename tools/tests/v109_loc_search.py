# -*- coding: utf-8 -*-
"""One-off: search the parsed localization table for a Chinese term and print keys."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
term = sys.argv[1]
path = os.path.join(ROOT, "data", "localization.json")
tbl = json.load(open(path, encoding="utf-8"))
print("top keys:", list(tbl)[:12])


def walk(node, prefix=""):
    """Yield (key, value) for every string leaf, whatever the nesting."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{prefix}{k}.")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{prefix}{i}.")
    elif isinstance(node, str):
        yield prefix.rstrip("."), node


n = 0
for k, v in walk(tbl):
    if term in v:
        print(f"{k}  =  {v}")
        n += 1
        if n > 40:
            break
print("hits:", n)
