# -*- coding: utf-8 -*-
"""一次性施工: 删 vassal_tenet_lines 方法 + VASSAL_TENET_MAX 常量 + facts 键。"""
import io
import re

P = r"D:\Roman\facts.py"
src = io.open(P, encoding="utf-8").read()

a = src.index("    def vassal_tenet_lines(self, cid, date=None, limit=None):")
b = src.index("    def rite_tenet_changes(self, cid, date=None):")
src = src[:a] + src[b:]

# facts 键: "vassal_tenets": f.vassal_tenet_lines(...) 两行
src2 = re.sub(r'\n *"vassal_tenets": f\.vassal_tenet_lines\([^)]*\),', "", src)
assert src2 != src, "facts 键未删"
src = src2

# 常量 VASSAL_TENET_MAX = 12 (连同其上方注释块)
m = re.search(r"(?:^#[^\n]*\n)*^VASSAL_TENET_MAX = 12\n", src, re.M)
if m:
    src = src[:m.start()] + src[m.end():]
else:
    src = src.replace("VASSAL_TENET_MAX = 12\n", "")

io.open(P, "w", encoding="utf-8", newline="").write(src)
print("done; vassal_tenet 残留:", src.count("vassal_tenet"), "; VASSAL_TENET_MAX 残留:",
      src.count("VASSAL_TENET_MAX"))
