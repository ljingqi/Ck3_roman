# -*- coding: utf-8 -*-
"""v112 只读探针：从指定缓存文件里抠出 played_legacy 链与每个链成员的档案。

不整载缓存（player_*.json 最大 240MB，json.load 会吃 1GB+ 内存）：
流式扫描文件，命中 "played_legacy": 即打印其后若干字节。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_legacy.py [缓存文件] [续读字节数]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")
    span = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    key = b'"played_legacy":'
    buf = b""
    hit = None
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(1 << 22)
            if not chunk:
                break
            buf += chunk
            i = buf.find(key)
            if i >= 0:
                hit = buf[i:i + span]
                break
            buf = buf[-len(key):]
    if hit is None:
        print("未找到 played_legacy")
        return 1
    print(hit.decode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
