# -*- coding: utf-8 -*-
"""v114 probe: crop the page's tree between two named beads (see a whole red path at once).

Usage: & tools\\py.ps1 tools\\tests\\v114_probe_span.py 洪天贵福 尼各老
"""
import importlib.util
import json
import os
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")


def main():
    a, b = (sys.argv[1:3] + ["洪天贵福", "尼各老"])[:2]
    spec = importlib.util.spec_from_file_location(
        "verify_v113", os.path.join(ROOT, "tools", "tests", "verify_v113.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raw = subprocess.run(["node", mod.write_harness(),
                          os.path.join(ROOT, "output", "洪氏2", "index.html")],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT).stdout
    case = next(c for c in json.loads(raw.strip().splitlines()[-1])["cases"] if c["k"] == 9)
    img = Image.open(os.path.join(ROOT, "logs", "v113_tree_k9.png")).convert("RGB")

    def find(nm):
        return [x for x in case["beads"] if x["texts"] and nm in (x["texts"][0] or "")]
    ba, bb = find(a), find(b)
    if not ba or not bb:
        print("找不到", a if not ba else "", b if not bb else "")
        return
    x0 = min(ba[0]["x"], bb[0]["x"]) - 120
    x1 = max(ba[0]["x"] + ba[0]["w"], bb[0]["x"] + bb[0]["w"]) + 120
    y0 = min(ba[0]["y"], bb[0]["y"]) - 150
    y1 = max(ba[0]["y"], bb[0]["y"]) + 220
    box = (max(0, int(x0)), max(0, int(y0)), min(img.width, int(x1)), min(img.height, int(y1)))
    out = os.path.join(ROOT, "logs", f"v114_span_{a}_{b}.png")
    img.crop(box).save(out)
    print(f"{a}→{b} {box} → {out}")


if __name__ == "__main__":
    main()
