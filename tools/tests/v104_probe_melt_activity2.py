# -*- coding: utf-8 -*-
"""v104 probe: dump activity_manager objects from a melt (streamed, slice-only json parse).

Usage: py tools/tests/v104_probe_melt_activity2.py <melt> [--host=ID] [--type=SUBSTR] [--all]
"""
import json
import lzma
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"


def stream(path, chunk=1 << 22):
    op = lzma.open if path.endswith(".xz") else open
    with op(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                return
            yield b


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = [a for a in sys.argv[1:] if a.startswith("--")]
    path = args[0] if args else DEFAULT
    host = None
    typesub = None
    for o in opts:
        if o.startswith("--host="):
            host = int(o.split("=", 1)[1])
        elif o.startswith("--type="):
            typesub = o.split("=", 1)[1]
    needle = b'"activity_manager"'
    buf = b""
    started = False
    depth = 0
    in_str = False
    esc = False
    out = None
    i = 0
    for chunk in stream(path):
        if not started:
            buf += chunk
            p = buf.find(needle)
            if p < 0:
                buf = buf[-64:]
                continue
            j = buf.find(b"{", p)
            if j < 0:
                buf = buf[p:]
                continue
            buf = buf[j:]
            started = True
            i = 0
        while i < len(buf):
            ch = buf[i:i + 1]
            if in_str:
                if esc:
                    esc = False
                elif ch == b"\\":
                    esc = True
                elif ch == b'"':
                    in_str = False
            else:
                if ch == b'"':
                    in_str = True
                elif ch == b"{":
                    depth += 1
                elif ch == b"}":
                    depth -= 1
                    if depth == 0:
                        out = buf[:i + 1]
                        break
            i += 1
        if out is not None:
            break
        buf = buf[max(0, i - 1):]
        i = 1
    if out is None:
        print("activity_manager not found / incomplete")
        return
    print("activity_manager JSON bytes", len(out))
    am = json.loads(out.decode("utf-8"))
    db = am.get("database") or {}
    print("activities", len(db))
    by_type = {}
    for aid, a in db.items():
        t = (a or {}).get("type") if isinstance(a, dict) else None
        by_type[t] = by_type.get(t, 0) + 1
    for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print("   ", t, n)
    for aid, a in db.items():
        if not isinstance(a, dict):
            continue
        t = str(a.get("type") or "")
        if typesub == "@none":
            if t:
                continue
        elif typesub and typesub not in t:
            continue
        if host is not None and a.get("host") != host:
            continue
        print("-" * 70)
        print("activity", aid, json.dumps(a, ensure_ascii=False)[:2500])


if __name__ == "__main__":
    main()
