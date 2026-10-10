# -*- coding: utf-8 -*-
"""临时取证：条件树里「none/any 节点下含 unknown 叶」的分布（第1问 chaplain 支线）。

`cond_match` 对 unknown 叶的承诺是「无值则永不匹配」，但该叶一旦落在 `none` 下面，
False 会翻成 True —— 这会伪造匹配。本脚本统计这种结构的分布。
"""
import json
import io
import os
import sys

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)


def walk(node, neg_ctx, hits, path):
    if not isinstance(node, dict):
        return
    if "unknown" in node or "unknown_not" in node:
        if neg_ctx:
            hits.append((path, node))
        return
    op = node.get("op")
    kids = node.get("children")
    if isinstance(kids, list):
        for i, k in enumerate(kids):
            walk(k, neg_ctx or op == "none", hits, path + "/%s[%d]" % (op, i))


def scan(fn, keypath):
    p = os.path.join(ROOT, "data", fn)
    if not os.path.exists(p):
        print(fn, "缺")
        return
    d = json.load(io.open(p, encoding="utf-8"))
    hits = []
    node = d
    for k in keypath:
        node = (node or {}).get(k)
    for name, arms in (node or {}).items():
        if not isinstance(arms, list):
            continue
        for i, a in enumerate(arms):
            walk(a.get("when"), False, hits, "%s#%d" % (name, i))
    print("%-26s 负语境下的 unknown 叶: %d" % (fn, len(hits)))
    for h in hits[:12]:
        print("   ", h[0], h[1])


scan("council_names.json", ["positions"])
scan("bishop_titles.json", [])
scan("court_positions.json", [])
