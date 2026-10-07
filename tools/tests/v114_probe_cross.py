# -*- coding: utf-8 -*-
"""v114 probe: is any drawn edge (above all a red one) crossed by a bead of another row?

The layout lives in JavaScript, so this runs the page's own script headlessly and inspects the
geometry it produced: every edge path's segments are tested against every bead rectangle.
Usage: & tools\\py.ps1 tools\\tests\\v114_probe_cross.py
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")


def main():
    spec = importlib.util.spec_from_file_location(
        "verify_v113", os.path.join(ROOT, "tools", "tests", "verify_v113.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    harness = mod.write_harness()
    raw = subprocess.run(["node", harness, os.path.join(ROOT, "output", "洪氏2", "index.html")],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT).stdout
    got = json.loads(raw.strip().splitlines()[-1])
    tree = json.load(open(os.path.join(ROOT, "output", "洪氏2", "data", "genealogy.json"),
                          encoding="utf-8"))
    N = {n["id"]: n for n in tree["nodes"]}
    for case in got["cases"]:
        k = case["k"]
        beads = case["beads"]
        hits = []
        for pa in case["paths"]:
            if pa["cls"] not in ("edge", "edge red", "spouse-link"):
                continue
            mm = re.fullmatch(r"M([-\d.]+),([-\d.]+) V([-\d.]+) H([-\d.]+) V([-\d.]+)", pa["d"])
            if mm:
                x0, y0, yb, x1, y1 = (float(mm.group(i)) for i in range(1, 6))
                segs = [("v", x0, y0, yb), ("h", yb, min(x0, x1), max(x0, x1)), ("v", x1, yb, y1)]
            else:
                mm = re.fullmatch(r"M([-\d.]+),([-\d.]+) H([-\d.]+)", pa["d"])
                if not mm:
                    continue
                x0, y0, x1 = (float(mm.group(i)) for i in range(1, 4))
                segs = [("h", y0, min(x0, x1), max(x0, x1))]
            for b in beads:
                for kind, a, lo, hi in segs:
                    if kind == "h":
                        if b["y"] < a < b["y"] + b["h"] and lo < b["x"] + b["w"] and hi > b["x"]:
                            hits.append((pa["cls"], pa["d"][:60],
                                         (b["id"], N.get(b["id"], {}).get("name", ""),
                                          b["x"], b["y"])))
                    else:
                        if b["x"] < a < b["x"] + b["w"] and lo < b["y"] + b["h"] and hi > b["y"]:
                            hits.append((pa["cls"], pa["d"][:60],
                                         (b["id"], N.get(b["id"], {}).get("name", ""),
                                          b["x"], b["y"])))
        print(f"== k={k}: 珠 {len(beads)} 折线 {len(case['paths'])} 交叠 {len(hits)}")
        seen = set()
        for cls, d, b in hits:
            key = (cls, d, b[0])
            if key in seen:
                continue
            seen.add(key)
            print(f"   {cls:10s} {d:55s} × {b[1]}(id{b[0]}) at x={b[2]:.0f},y={b[3]:.0f}")


if __name__ == "__main__":
    main()
