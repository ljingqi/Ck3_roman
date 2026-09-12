# -*- coding: utf-8 -*-
"""打印《家室列传》开篇全文 (只读), 核对子女归属口径。"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "output", "柳特佩特",
                    "潘杜尔夫·柳特佩特(848)_传记_878_01_01.md")
text = io.open(PATH, encoding="utf-8").read()
m = re.search(r"^##\s*[^\n]*《家室列传》[^\n]*$(.*?)(?=^##\s|\Z)",
              text, re.S | re.M)
print(m.group(1).strip() if m else "未找到《家室列传》")
