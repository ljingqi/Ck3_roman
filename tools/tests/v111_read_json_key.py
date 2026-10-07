# -*- coding: utf-8 -*-
"""v111 探查：从很大的 JSON（缓存/熔件，可 .xz）里流式取一个顶层键的值。

用法：
    & tools\\py.ps1 tools\\tests\\v111_read_json_key.py <文件> <键> [<键> ...]
只做花括号/方括号配平，不看结构，因此不必把 200MB 的缓存读进内存。
"""
import json
import lzma
import os
import sys


def _open(path):
    return lzma.open(path, "rb") if path.endswith(".xz") else open(path, "rb")


def _balanced(buf, start):
    """buf[start] is '{' or '['; returns the balanced slice (string-aware)."""
    op = buf[start:start + 1]
    cl = b"}" if op == b"{" else b"]"
    depth, i, q, esc = 0, start, False, False
    while i < len(buf):
        ch = buf[i:i + 1]
        if q:
            if esc:
                esc = False
            elif ch == b"\\":
                esc = True
            elif ch == b'"':
                q = False
        elif ch == b'"':
            q = True
        elif ch in (b"{", b"["):
            depth += 1
        elif ch in (b"}", b"]"):
            depth -= 1
            if depth == 0 and ch == cl:
                return buf[start:i + 1]
        i += 1
    return b""


def value(path, key, keep=4 << 20):
    needle = ('"%s":' % key).encode()
    buf = b""
    with _open(path) as fp:
        while True:
            chunk = fp.read(8 << 20)
            if not chunk:
                return None
            buf = buf + chunk
            while True:
                i = buf.find(needle)
                if i < 0:
                    break
                j = i + len(needle)
                while j < len(buf) and buf[j:j + 1] in (b" ", b"\n", b"\t", b"\r"):
                    j += 1
                if j >= len(buf):
                    break
                if buf[j:j + 1] not in (b"{", b"["):
                    # a scalar (string/number/bool)
                    k = j
                    q = buf[j:j + 1] == b'"'
                    if q:
                        k += 1
                        while k < len(buf) and buf[k:k + 1] != b'"':
                            k += 2 if buf[k:k + 1] == b"\\" else 1
                    else:
                        while k < len(buf) and buf[k:k + 1] not in (b",", b"}", b"\n"):
                            k += 1
                    try:
                        return json.loads(buf[j:k + 1].decode("utf-8", "replace"))
                    except ValueError:
                        break
                obj = _balanced(buf, j)
                if not obj:
                    break                    # needs more data
                try:
                    return json.loads(obj.decode("utf-8", "replace"))
                except ValueError:
                    break
            if len(buf) > keep:
                buf = buf[-keep:]
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    path = sys.argv[1]
    print("%s (%d MB)" % (os.path.basename(path), os.path.getsize(path) >> 20))
    for key in sys.argv[2:]:
        v = value(path, key)
        print("\n#### %s = %s" % (key, json.dumps(v, ensure_ascii=False)[:4000]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
