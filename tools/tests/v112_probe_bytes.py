# -*- coding: utf-8 -*-
"""v112 只读探针：统计缓存文件里出现某个字节串的次数（流式）。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_bytes.py <文件> <字节串> [melt_密钥...]
例:   & tools\\py.ps1 tools\\tests\\v112_probe_bytes.py output\\洪氏2\\data\\player_207044.json twin
"""
import os
import sys


def main():
    path = sys.argv[1]
    pats = [a.encode("utf-8") for a in sys.argv[2:]]
    if not pats:
        print("需要一个待查字节串")
        return 2
    counts = {p: 0 for p in pats}
    tail = max(len(p) for p in pats) - 1
    buf = b""
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(1 << 22)
            if not chunk:
                break
            data = buf + chunk
            for p in pats:
                counts[p] += data.count(p)
            buf = data[-tail:] if tail > 0 else b""
    for p in pats:
        print("%-30s %d 次" % (p.decode("utf-8", "replace"), counts[p]))
    print("文件: %s  (%.1f MB)" % (os.path.relpath(path), os.path.getsize(path) / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
