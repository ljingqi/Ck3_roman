# -*- coding: utf-8 -*-
"""Row spans of the 宝塔式 layout — how wide each generation row really is, and where it sits."""
import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")


def harness():
    spec = importlib.util.spec_from_file_location(
        "verify_v113", os.path.join(ROOT, "tools", "tests", "verify_v113.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.write_harness()


raw = subprocess.run(["node", harness(), os.path.join(ROOT, "output", "洪氏2", "index.html")],
                     capture_output=True, text=True, encoding="utf-8", cwd=ROOT).stdout
got = json.loads(raw.strip().splitlines()[-1])
tree = json.load(open(os.path.join(ROOT, "output", "洪氏2", "data", "genealogy.json"),
                      encoding="utf-8"))
gen = {n["id"]: n["gen"] for n in tree["nodes"]}
case = got["cases"][0]
rows = {}
for b in case["beads"]:
    g = gen[b["id"]]
    r = rows.setdefault(g, [])
    r.append(b)
print("画布", case["view"])
for g in sorted(rows):
    xs = sorted(b["x"] for b in rows[g])
    print("  %d世 珠 %2d  span %5d .. %5d  宽 %5d" % (g, len(rows[g]), xs[0], xs[-1],
                                                      xs[-1] - xs[0]))
