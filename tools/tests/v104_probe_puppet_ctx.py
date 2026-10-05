# -*- coding: utf-8 -*-
"""v104 probe 2: 定位熔件里的傀儡链与会议痕迹（只做字节扫描 + 少量切片）。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_puppet_ctx.py <melt> [needle ...]
"""
import json
import lzma
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"
NEEDLES = ['"characters"', '"puppeteers"', '"puppeteer"', 'theological_agent_puppet',
           'activity_ecumenical_council', 'catalyst_secular_hosted_ecumenical_council',
           '"landed_data"', '"alive_data"', '"dead_data"', '"135480"']


def load_bytes(path):
    if path.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    needles = [a.encode("utf-8") for a in sys.argv[2:]] or [n.encode("utf-8") for n in NEEDLES]
    data = load_bytes(path)
    print("melt", path)
    print("decompressed bytes", len(data))
    for n in needles:
        print("=" * 72)
        print(n.decode(), "count", data.count(n))
        p, shown = 0, 0
        while shown < 4:
            p = data.find(n, p)
            if p < 0:
                break
            print("-" * 60, "at", p)
            print(data[max(0, p - 300):p + 500].decode("utf-8", "replace"))
            p += 1
            shown += 1


if __name__ == "__main__":
    main()
