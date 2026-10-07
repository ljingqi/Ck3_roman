# -*- coding: utf-8 -*-
"""v114 probe: for each piece's tree (k), is every transmission path visible and connected?"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
t = json.load(io.open(os.path.join(ROOT, "output", "洪氏2", "data", "genealogy.json"),
                      encoding="utf-8"))
N = {n["id"]: n for n in t["nodes"]}
K = len(t["chain"])
for k in range(1, K + 1):
    keep = {n["id"] for n in t["nodes"] if (n["from_k"] or 1) <= k}
    red = {(a, b) for a, b, i in t["red_edges"] if i <= k - 2}
    lines = []
    for i, p in enumerate(t["pairs"]):
        if i > k - 2:
            continue
        chain_vis = [x for x in p if x in keep]
        missing = [x for x in p if x not in keep]
        # connected? every consecutive pair of the path must be an edge (and both visible)
        broken = []
        for u, v in zip(p, p[1:]):
            e = (u, v) if (u, v) in red else ((v, u) if (v, u) in red else None)
            if e is None or u not in keep or v not in keep:
                broken.append(f"{N[u]['name']}→{N[v]['name']}" if e else
                              f"缺边 {N[u]['name']}~{N[v]['name']}")
        if broken:
            lines.append(f"  pair{i+1} 断: {broken}  路径="
                         + "→".join(f"{N[x]['name']}(k{N[x]['from_k']})" for x in p))
    print(f"== k={k}: 可见 {len(keep)}/{len(t['nodes'])} 节点, 红线 {len(red)} 段"
          + ("" if not lines else "\n" + "\n".join(lines)))
