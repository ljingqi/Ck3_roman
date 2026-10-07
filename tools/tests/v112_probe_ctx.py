# -*- coding: utf-8 -*-
"""v112 只读探针：在缓存文件里找某个字节串并打印上下文（流式）。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_ctx.py <文件> <字节串> [前字节] [后字节] [最多命中数]
"""
import os
import sys


def main():
    path = sys.argv[1]
    pat = sys.argv[2].encode("utf-8")
    span = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    after = int(sys.argv[4]) if len(sys.argv) > 4 else span
    limit = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    print("文件: %s (%.1f MB)" % (os.path.relpath(path), os.path.getsize(path) / 1048576.0))
    n = 0
    off = 0
    buf = b""
    base = 0
    with open(path, "rb") as fp:
        while n < limit:
            chunk = fp.read(1 << 22)
            if not chunk:
                break
            data = buf + chunk
            start = 0
            while n < limit:
                i = data.find(pat, start)
                if i < 0:
                    break
                a = max(0, i - span)
                b = min(len(data), i + len(pat) + after)
                print("\n--- 命中 #%d  文件偏移 ~%d ---" % (n + 1, base - len(buf) + i))
                print(data[a:b].decode("utf-8", "replace"))
                n += 1
                start = i + len(pat)
            keep = max(len(pat), 64)
            buf = data[-keep:]
            base += len(data) - len(buf) if False else len(chunk)
    if n == 0:
        print("无命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())
