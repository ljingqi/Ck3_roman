# -*- coding: utf-8 -*-
"""v104 probe 3: 看熔件顶层骨架，并回溯某个偏移属于哪个容器。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_skeleton.py <melt> [offset]
"""
import lzma
import re
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"
KEYS = ['"characters"', '"living"', '"dead"', '"dead_prunable"', '"landed_titles"',
        '"dynasties"', '"activity_manager"', '"situation_manager"', '"religion"',
        '"rites"', '"faiths"', '"court_data"', '"opinions"', '"memories"',
        '"scripted_relations"', '"metadata"', '"played_legacy"', '"dynasty_house"']


def load_bytes(path):
    if path.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    data = load_bytes(path)
    print("melt", path, "bytes", len(data))
    print("[head 600]", data[:600].decode("utf-8", "replace"))
    print("[tail 300]", data[-300:].decode("utf-8", "replace"))
    print("=" * 72)
    for k in KEYS:
        b = k.encode("utf-8")
        n = data.count(b)
        first = data.find(b)
        print("%-28s count=%-7d first=%d" % (k, n, first))
    if len(sys.argv) > 2:
        off = int(sys.argv[2])
        print("=" * 72)
        print("回溯 offset", off)
        back = data[max(0, off - 3000):off]
        # 找最近的 ":{" 前的键名
        hits = list(re.finditer(rb'"([A-Za-z_][A-Za-z0-9_]*)":\{', back))
        for m in hits[-8:]:
            print("   ...", m.group(1).decode(), "at", max(0, off - 3000) + m.start())
        print("-" * 60)
        print(back[-1200:].decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
