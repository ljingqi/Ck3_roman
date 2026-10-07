# -*- coding: utf-8 -*-
"""v114 probe: scale the painted full tree into readable halves (see the whole 家谱图 at once)."""
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
src = os.path.join(ROOT, "logs", "v113_tree_k9.png")
img = Image.open(src).convert("RGB")
w, h = img.size
for i, (x0, x1, name) in enumerate([(0, w // 2, "left"), (w // 2, w, "right")]):
    part = img.crop((x0, 0, x1, h))
    scale = min(1.0, 1500.0 / part.width)
    part = part.resize((int(part.width * scale), int(part.height * scale)), Image.LANCZOS)
    out = os.path.join(ROOT, "logs", f"v114_full_{name}.png")
    part.save(out)
    print(f"{out} {part.width}×{part.height} (源 {x1 - x0}×{h})")
