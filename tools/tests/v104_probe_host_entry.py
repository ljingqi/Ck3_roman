# -*- coding: utf-8 -*-
"""v104 probe 5: 抽取传主 135480 的活人条目，看 puppet 槽位与所在地。

只对「单个角色条目」这一小片 json.loads。
用法: & tools\\py.ps1 tools\\tests\\v104_probe_host_entry.py <melt> [cid]
"""
import gc
import json
import lzma
import re
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1056_01_01.json.xz"
CID = "135480"
ENTRY_RE = re.compile(rb'"(\d{1,12})":\{"first_name":')


def load_bytes(path):
    if path.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()


def slice_value(data, start):
    ch0 = data[start:start + 1]
    if ch0 != b"{":
        raise ValueError("not an object start: %r" % ch0)
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
    """在 living 容器里取该角色条目（返回 (字节区间, 对象)）。"""
    needle = b'"' + cid.encode() + b'":{"first_name":'
    p = data.find(needle)
    if p < 0:
        return None, None
    brace = data.find(b"{", p)
    end = slice_value(data, brace)
    blob = data[brace:end]
    try:
        return (p, brace, end), json.loads(blob.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return (p, brace, end), {"__error__": str(exc)}


def main():
    paths = sys.argv[1:] or [DEFAULT]
    cid = CID
    if paths and paths[-1].isdigit():
        cid = paths.pop()
    for path in paths:
        data = load_bytes(path)
        print("=" * 78)
        print("melt", path, "bytes", len(data))
        span, obj = entry_of(data, cid)
        print("条目字节区间", span)
        if not obj:
            continue
        print("条目顶层键:", sorted(obj.keys()))
        print("first_name:", obj.get("first_name"), "| birth:", obj.get("birth"))
        al = obj.get("alive_data")
        if isinstance(al, dict):
            print("alive_data 键:", sorted(al.keys()))
            for k in ("puppets", "puppeteer", "location", "variables"):
                if k in al:
                    print("  alive_data.%s =" % k,
                          json.dumps(al[k], ensure_ascii=False)[:1500])
            if "variables" in al and isinstance(al["variables"], dict):
                for item in (al["variables"].get("list") or []):
                    if "puppet" in json.dumps(item, ensure_ascii=False):
                        print("  variables.list:", json.dumps(item, ensure_ascii=False))
        for k in ("puppets", "puppeteer", "landed_data", "court_data",
                  "government", "titles", "domain"):
            if k in obj:
                print("  %s =" % k, json.dumps(obj[k], ensure_ascii=False)[:800])
        # 是否傀儡主：整份熔件里有多少条 alive_data.puppets
        print("  熔件全局 \"puppets\":[ 出现", data.count(b'"puppets":['), "次")
        del data
        gc.collect()


if __name__ == "__main__":
    main()
