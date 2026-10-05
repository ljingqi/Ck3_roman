# -*- coding: utf-8 -*-
"""v104 probe 13: 打印 puppets 数组前后的原文窗口，定位它挂在角色条目的哪个子对象下。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_puppets_window.py <melt> [needle] [n]
"""
import lzma
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"
NEEDLE = b'"puppets":['


def load_bytes(path):
    if path.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    needle = sys.argv[2].encode() if len(sys.argv) > 2 else NEEDLE
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    back = int(sys.argv[4]) if len(sys.argv) > 4 else 2600
    data = load_bytes(path)
    print("melt", path, "bytes", len(data))
    p, shown = 0, 0
    while shown < n:
        p = data.find(needle, p)
        if p < 0:
            break
        print("=" * 78)
        print("offset", p)
        print("[前 %d 字节]" % back)
        print(data[max(0, p - back):p].decode("utf-8", "replace"))
        print("[后 300 字节]")
        print(data[p:p + 300].decode("utf-8", "replace"))
        p += 1
        shown += 1


if __name__ == "__main__":
    main()
