# -*- coding: utf-8 -*-
"""v114 probe: crop the page's own tree geometry around named beads (see the red line by eye).

Usage: & tools\\py.ps1 tools\\tests\\v114_probe_crop.py 洪七公 [洪卡特琳 ...]
"""
import importlib.util
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")


def harness_path():
    spec = importlib.util.spec_from_file_location(
        "verify_v113", os.path.join(ROOT, "tools", "tests", "verify_v113.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.write_harness()


def main():
    names = sys.argv[1:] or ["洪七公"]
    raw = subprocess.run(["node", harness_path(),
                          os.path.join(ROOT, "output", "洪氏2", "index.html")],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT).stdout
    got = json.loads(raw.strip().splitlines()[-1])
    case = next(c for c in got["cases"] if c["k"] == 9)
    img = Image.open(os.path.join(ROOT, "logs", "v113_tree_k9.png")).convert("RGB")
    for nm in names:
        hits = [b for b in case["beads"] if b["texts"] and nm in (b["texts"][0] or "")]
        if not hits:
            print("找不到珠粒", nm)
            continue
        for b in hits:
            x, y, bw, bh = b["x"], b["y"], b["w"], b["h"]
            box = (max(0, int(x - 700)), max(0, int(y - 260)),
                   min(img.width, int(x + bw + 700)), min(img.height, int(y + bh + 500)))
            out = os.path.join(ROOT, "logs", f"v114_crop_{nm}.png")
            img.crop(box).save(out)
            print(f"{nm} x={x:.0f} y={y:.0f} → {out} {box}")


if __name__ == "__main__":
    main()
