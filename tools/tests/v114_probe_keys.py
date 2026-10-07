# -*- coding: utf-8 -*-
"""v114 probe: the article keys and titles of biography.py."""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
s = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "biography.py"), encoding="utf-8").read()
for m in re.finditer(r'"key":\s*"([a-z_]+)",\s*"title":\s*"([^"]+)"', s):
    print(m.group(1), m.group(2))
