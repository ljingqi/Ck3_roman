# -*- coding: utf-8 -*-
"""v104 probe 14: 定位 puppets 挂在角色条目的哪个子对象（playable_data / alive_data / 顶层）。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_puppet_path.py <melt> [cid ...]
"""
import gc
import json
import lzma
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"
CIDS = ["135480", "67179401"]


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


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    cids = sys.argv[2:] or CIDS
    data = load_bytes(path)
    print("melt", path, "bytes", len(data))
    for cid in cids:
        needle = b'"' + cid.encode() + b'":{"first_name":'
        p = data.find(needle)
        print("=" * 78)
        print("cid", cid, "entry at", p)
        if p < 0:
            continue
        brace = data.find(b"{", p)
        end = slice_value(data, brace)
        blob = data[brace:end]
        print("  条目字节", len(blob))
        obj = json.loads(blob.decode("utf-8"))
        print("  顶层键:", sorted(obj.keys()))
        for sub in ("playable_data", "landed_data", "alive_data", "court_data"):
            v = obj.get(sub)
            if isinstance(v, dict):
                ks = sorted(v.keys())
                print("  %s 键:" % sub, ks)
                for k in ks:
                    if "puppet" in k or "tenet" in k or "doctrine" in k or "cooldown" in k:
                        print("     %s.%s = %s" % (sub, k,
                              json.dumps(v[k], ensure_ascii=False)[:600]))
            elif v is not None:
                print("  %s = %s" % (sub, json.dumps(v, ensure_ascii=False)[:200]))
        for k in ("puppets", "puppet"):
            if k in obj:
                print("  顶层 %s = %s" % (k, json.dumps(obj[k], ensure_ascii=False)[:400]))
    del data
    gc.collect()


if __name__ == "__main__":
    main()
