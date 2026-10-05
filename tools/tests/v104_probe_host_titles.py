# -*- coding: utf-8 -*-
"""v104 probe 6: 传主 135480 的全部头衔 / 政体 / 教省关联 / 活人条目全文。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_host_titles.py <melt> [cid]
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
        return None, None
    brace = data.find(b"{", p)
    end = slice_value(data, brace)
    return (p, brace, end), json.loads(data[brace:end].decode("utf-8"))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    cid = sys.argv[2] if len(sys.argv) > 2 else CID
    data = load_bytes(path)
    print("melt", path, "bytes", len(data))

    print("=" * 78)
    print("[1] 传主条目全文（裁剪 dna）")
    _span, obj = entry_of(data, cid)
    if obj:
        if "dna" in obj:
            obj["dna"] = obj["dna"][:20] + "..."
        print(json.dumps(obj, ensure_ascii=False, indent=1)[:9000])

    print("=" * 78)
    print("[2] landed_titles 里他的头衔")
    lt = data.find(b'"landed_titles"')
    print("landed_titles at", lt)
    brace = data.find(b"{", lt)
    end = slice_value(data, brace)
    print("landed_titles 字节", end - brace)
    blob = data[brace:end]
    try:
        lto = json.loads(blob.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("!!! json.loads 失败", exc)
        lto = None
    if isinstance(lto, dict):
        print("键:", sorted(lto.keys())[:10])
        inner = lto.get("landed_titles") if isinstance(lto.get("landed_titles"), dict) else lto
        if isinstance(inner, dict):
            print("头衔条数", len(inner))
            hit = 0
            for tid, t in inner.items():
                if not isinstance(t, dict):
                    continue
                holder = t.get("holder")
                hist = t.get("history") or {}
                last_ids = []
                if isinstance(hist, dict):
                    for _d, v in list(hist.items())[-3:]:
                        if isinstance(v, dict):
                            last_ids.append(v.get("character") or v.get("holder"))
                        else:
                            last_ids.append(v)
                if str(holder) == cid or cid in [str(x) for x in last_ids]:
                    hit += 1
                    keep = {k: v for k, v in t.items()
                            if k in ("holder", "key", "name", "de_jure_liege", "tier",
                                     "clerical_region", "history", "title_name_data",
                                     "landless", "is_head_of_faith", "government",
                                     "claim", "elective", "succession")}
                    print("-" * 60, "title id", tid)
                    print(json.dumps(keep, ensure_ascii=False)[:2500])
            print("命中头衔数", hit)
            # 全库 clerical_region 头衔中有无持有人 = 他
            cr = [(k, v.get("holder")) for k, v in inner.items()
                  if isinstance(v, dict) and v.get("clerical_region") is not None]
            print("库内带 clerical_region 的头衔数", len(cr), cr[:12])
    del data
    gc.collect()


if __name__ == "__main__":
    main()
