# -*- coding: utf-8 -*-
"""v104 probe 11: 把熔件里全部含 ecumenical_council 的串按「后随词」归类，判定有无活动/事件残留。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_ecum_scan.py <melt>
"""
import collections
import gc
import lzma
import re
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"


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

    tail = collections.Counter()
    samples = {}
    for m in re.finditer(rb'ecumenical_council', data):
        o = m.start()
        # 取后随 60 字节里的「标识符尾巴」
        nxt = re.match(rb'[A-Za-z0-9_.]*', data[o + 18:o + 80]).group(0)
        key = nxt.decode("utf-8", "replace")
        tail[key] += 1
        if key not in samples:
            samples[key] = data[max(0, o - 160):o + 220].decode("utf-8", "replace")
    print("=" * 78)
    print("后随词分布（共 %d 处）" % sum(tail.values()))
    for k, v in tail.most_common(40):
        print("   %-40s %d" % ("ecumenical_council" + k, v))
    print("=" * 78)
    for k, v in tail.most_common(12):
        print("-" * 60, "ecumenical_council" + k, v)
        print("   ", samples[k].replace("\n", " "))
    del data
    gc.collect()


if __name__ == "__main__":
    main()
