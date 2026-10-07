# -*- coding: utf-8 -*-
"""v113 probe: draw the page's real tree geometry to PNG so the layout can be seen (no melt).

The numbers come from the page's own renderer (logs/v113_tree_harness.mjs); this only paints them,
so the picture shows exactly what the browser would lay out."""
import io
import importlib.util
import json
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
FONTS = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
         r"C:\Windows\Fonts\simsun.ttc"]


def harness_path():
    spec = importlib.util.spec_from_file_location(
        "verify_v113", os.path.join(ROOT, "tools", "tests", "verify_v113.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.write_harness()


def font(size):
    for p in FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def metrics(k):
    raw = subprocess.run(["node", harness_path(),
                          os.path.join(ROOT, "output", "洪氏2", "index.html")],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT).stdout
    got = json.loads(raw.strip().splitlines()[-1])
    return next(c for c in got["cases"] if c["k"] == k), got["K"]


def main():
    case, K = metrics(9)
    w, h = case["view"]
    img = Image.new("RGB", (int(w), int(h)), "#fdfaf0")
    d = ImageDraw.Draw(img)
    for pa in case["paths"]:
        mm = re.fullmatch(r"M([-\d.]+),([-\d.]+) H([-\d.]+) V([-\d.]+) H([-\d.]+)", pa["d"])
        col = {"edge": "#4a4238", "edge red": "#b3352a", "edge dashed": "#b3352a"}.get(pa["cls"])
        if not mm or not col:
            continue
        x0, y0, ex, cy, x1 = (float(g) for g in mm.groups())
        wide = 2 if pa["cls"] != "edge" else 1
        d.line([(x0, y0), (ex, y0), (ex, cy), (x1, cy)], fill=col, width=wide)
    for pa in case["paths"]:
        m2 = re.fullmatch(r"M([-\d.]+),([-\d.]+) V([-\d.]+)", pa["d"])
        if m2 and pa["cls"] == "spouse-link":
            x, y0, y1 = (float(g) for g in m2.groups())
            d.line([(x, y0), (x, y1)], fill="#a08a5e", width=1)
    fn, fy, ft = font(13), font(10), font(11)
    for b in case["beads"]:
        x, y, bw, bh = b["x"], b["y"], b["w"], b["h"]
        subj, kin = "subj" in b["cls"], "kin" in b["cls"]
        fill = "#fdf3e2" if subj else ("#f7f4ea" if kin else "#fffdf6")
        edge = "#b3352a" if subj else "#8d7f61"
        d.rounded_rectangle([x, y, x + bw, y + bh], radius=4, fill=fill, outline=edge,
                            width=2 if subj else 1)
        d.text((x + bw / 2, y + 13), b["texts"][0] if b["texts"] else "", font=fn,
               fill="#2b2419", anchor="mm")
        if len(b["texts"]) > 1 and b["texts"][1]:
            d.text((x + bw / 2, y + 26), b["texts"][1], font=ft, fill="#8a7a55", anchor="mm")
        if b["tog"]:
            d.text((x + bw - 12, y + bh / 2), b["tog"], font=ft, fill="#6f6247", anchor="mm")
    for g in range(1, 20):
        pass
    out = os.path.join(ROOT, "logs", "v113_tree_k9.png")
    img.save(out)
    print(f"{out}  {int(w)}×{int(h)}  珠粒 {case['bead_count']}  折线 {len(case['paths'])}")
    # a crop of the top-left area at full size, easier to read
    img.crop((0, 0, min(int(w), 900), min(int(h), 700))).save(
        os.path.join(ROOT, "logs", "v113_tree_k9_crop.png"))


if __name__ == "__main__":
    main()
