# -*- coding: utf-8 -*-
import re
from collections import Counter

lines = open(r"logs/v86_rite0_full.txt", encoding="utf-8").read().splitlines()
c = Counter()
names = {}
for ln in lines:
    m = re.search(r'"status": "([a-z]+)"', ln)
    if m:
        c[m.group(1)] += 1
        names.setdefault(m.group(1), []).append(ln.strip())
print(dict(c))
for k, v in names.items():
    print("---", k, len(v))
    for x in v:
        print("   ", x)
