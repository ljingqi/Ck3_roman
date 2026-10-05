# -*- coding: utf-8 -*-
"""v104 probe 12: 反查「传主把谁当傀儡」+ 传主条目里的大公会议事件标志。

方法验证：先用已知傀儡主（67179401）验证检索口径，再查传主。
用法: & tools\\py.ps1 tools\\tests\\v104_probe_puppet_reverse.py <melt> [cid ...]
"""
import gc
import json
import lzma
import re
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"
CIDS = ["135480", "67179401"]
ENTRY_RE = re.compile(rb'"(\d{1,12})":\{"first_name":')


def load_bytes(path):
    if path.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()


def slice_value(data, start):
    depth, i, in_str, esc = 0, start, False, False
    while i < len(data):
        c = data[i:i + 1]
        if in_str:
            if esc:
                esc = False
            elif c == b"\\":
                esc = True
            elif c == b'"':
                in_str = False
        else:
            if c == b'"':
                in_str = True
            elif c in (b"{", b"["):
                depth += 1
            elif c in (b"}", b"]"):
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return len(data)


def entry_of(data, cid):
    needle = b'"' + cid.encode() + b'":{"first_name":'
    p = data.find(needle)
    if p < 0:
        return None
    brace = data.find(b"{", p)
    end = slice_value(data, brace)
    return data[brace:end]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    cids = sys.argv[2:] or CIDS
    data = load_bytes(path)
    print("melt", path, "bytes", len(data))

    # 所有 puppeteers 列表项（用「向后 400 字节内找 identity」的宽口径）
    print("=" * 78)
    print("[1] 反向：谁的 puppeteers 列表里出现目标 cid（宽口径）")
    marks = [m.start() for m in re.finditer(rb'"name":"puppeteers"', data)]
    print("  puppeteers 列表项数（按 name 计）:", len(marks))
    for cid in cids:
        hits = []
        pat = b'"identity":' + cid.encode() + b"}"
        for off in marks:
            seg = data[off:off + 400]
            if pat in seg:
                owner = None
                back = data[max(0, off - 300000):off]
                m2 = list(ENTRY_RE.finditer(back))
                if m2:
                    owner = m2[-1].group(1).decode()
                hits.append((off, owner))
        print("  cid", cid, "命中", len(hits), hits[:6])

    # 传主条目里的大公会议相关变量 / 冷却
    print("=" * 78)
    print("[2] 目标条目内的会议相关字符串")
    for cid in cids:
        blob = entry_of(data, cid)
        if blob is None:
            print("  cid", cid, "条目未找到")
            continue
        print("-" * 60, "cid", cid, "条目字节", len(blob))
        for m in re.finditer(rb'[a-z_."]*council[a-z_."0-9]*', blob):
            o, e = m.start(), m.end()
            print("   ", blob[max(0, o - 60):e + 60].decode("utf-8", "replace"))
        obj = None
        try:
            obj = json.loads(blob.decode("utf-8"))
        except Exception:
            pass
        if isinstance(obj, dict):
            al = obj.get("alive_data") or {}
            print("   alive_data.puppets =",
                  json.dumps(al.get("puppets"), ensure_ascii=False))
            print("   alive_data.activity_data =",
                  json.dumps(al.get("activity_data"), ensure_ascii=False)[:500])
    del data
    gc.collect()


if __name__ == "__main__":
    main()
