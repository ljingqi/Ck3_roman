# -*- coding: utf-8 -*-
"""v112 只读：缓存里的死因串频次（确认 disappearance 的 reason 字面量）。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_reasons.py [缓存.json]
"""
import collections
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "output", "洪氏2", "data", "player_207044.json")
    t = io.open(p, encoding="utf-8", errors="replace").read()
    c = collections.Counter(re.findall(r'"reason":\s*"([a-z_]+)"', t))
    print("总字符 %d" % len(t))
    for k, v in c.most_common(20):
        print("  %-28s %d" % (k, v))
    print("含 disappearance 的 reason:",
          sorted({k for k in c if "disappear" in k}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
