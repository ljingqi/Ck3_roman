# -*- coding: utf-8 -*-
"""v112 只读探针：在指定缓存文件里查一批角色 id 是否有档案（流式，不整载）。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_cids.py <缓存文件> <cid> [cid...]
"""
import os
import sys


def main():
    path = sys.argv[1]
    cids = sys.argv[2:]
    keys = [('"%s":' % c).encode("utf-8") for c in cids]
    found = {c: False for c in cids}
    buf = b""
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(1 << 22)
            if not chunk:
                break
            buf += chunk
            for c, k in zip(cids, keys):
                if not found[c] and k in buf:
                    found[c] = True
            buf = buf[-64:]
    for c in cids:
        print("%-14s %s" % (c, "有档案" if found[c] else "无（或未出现该键）"))
    print("文件: %s  (%.1f MB)" % (os.path.relpath(path), os.path.getsize(path) / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
