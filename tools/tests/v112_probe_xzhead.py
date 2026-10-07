# -*- coding: utf-8 -*-
"""v112 只读探针：不解全包，流式 xz 解压打印开头若干字节。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_xzhead.py <xz 文件> [打印字节数]
"""
import lzma
import os
import sys


def main():
    path = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    out = b""
    with lzma.open(path, "rb") as fp:
        while len(out) < n:
            chunk = fp.read(65536)
            if not chunk:
                break
            out += chunk
    print("文件 %s (%.1f MB)" % (os.path.basename(path), os.path.getsize(path) / 1048576.0))
    print(out[:n].decode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
