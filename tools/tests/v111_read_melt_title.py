# -*- coding: utf-8 -*-
"""v111 探查：从熔件（可为 .json 或 .json.xz）里精确取一个头衔的原始对象。

熔件是按存档逐年落的，`melt_<年>_01_01.json[.xz]` 里的 `title_name_data` 就是**那一年存档里**
的值。要看「某年游戏显示的动态名到底是什么」，只能看那一年的熔件，不能看最后一份。

用法：
    & tools\\py.ps1 tools\\tests\\v111_read_melt_title.py <melt文件> <头衔id> [<头衔id> ...]
流式解压 + 花括号配平，不把整份熔件读进内存。
"""
import io
import json
import lzma
import os
import re
import sys


def _open(path):
    if path.endswith(".xz"):
        return lzma.open(path, "rb")
    return open(path, "rb")


def _balanced(buf, start):
    """The object starting at buf[start] == '{', brace-balanced, string-aware."""
    depth = 0
    i = start
    q = False
    esc = False
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
        elif ch == b"{":
            depth += 1
        elif ch == b"}":
            depth -= 1
            if depth == 0:
                return buf[start:i + 1]
        i += 1
    return b""


def find(path, tid, keep=32 << 20):
    """Every landed-title object introduced by '"<tid>":' (streamed, brace-balanced)."""
    needle = ('"%s":' % tid).encode()
    hits = []
    buf = b""
    with _open(path) as fp:
        while True:
            chunk = fp.read(8 << 20)
            if not chunk:
                break
            buf = buf + chunk
            while True:
                i = buf.find(needle)
                if i < 0:
                    break
                j = buf.find(b"{", i)
                if j < 0:
                    break
                obj = _balanced(buf, j)
                if not obj:
                    break            # object straddles the chunk edge: read more and retry
                if b'"title_name_data"' in obj or b'"de_jure' in obj:
                    try:
                        hits.append(json.loads(obj.decode("utf-8", "replace")))
                    except ValueError:
                        pass
                buf = buf[:j] + buf[j + len(obj):]
            if len(buf) > keep:
                buf = buf[-keep:]
    return hits


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    path = sys.argv[1]
    print("熔件 %s (%d MB)" % (os.path.basename(path), os.path.getsize(path) >> 20), flush=True)
    for tid in sys.argv[2:]:
        hits = find(path, tid)
        print("\n#### %s — %d 处命中" % (tid, len(hits)))
        for h in hits:
            print("   key=%s" % h.get("key"))
            print("   title_name_data=%s" % json.dumps(h.get("title_name_data"),
                                                       ensure_ascii=False))
            print("   holder=%s date=%s nomad_name_type=%s" % (
                h.get("holder"), h.get("date"), h.get("nomad_name_type")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
