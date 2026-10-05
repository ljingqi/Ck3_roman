# -*- coding: utf-8 -*-
"""v104 probe 7: 传主是不是信仰/礼仪之首，以及大公会议的信仰级留痕。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_faith_rite.py <melt> [cid]
"""
import gc
import json
import lzma
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"
CID = "135480"


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


def container(data, key):
    k = data.find(b'"' + key.encode() + b'":')
    if k < 0:
        return None, None
    brace = data.find(b"{", k)
    end = slice_value(data, brace)
    return (brace, end), data[brace:end]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    cid = sys.argv[2] if len(sys.argv) > 2 else CID
    data = load_bytes(path)
    print("melt", path, "bytes", len(data))

    for key in ("faiths", "rites"):
        span, blob = container(data, key)
        print("=" * 78)
        print("[%s] span=%s bytes=%s" % (key, span, len(blob) if blob else None))
        if blob is None:
            continue
        try:
            obj = json.loads(blob.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print("  !!! json.loads 失败", exc)
            continue
        print("  顶层键:", sorted(obj.keys())[:10])
        if key == "faiths":
            db = obj.get("database") or obj
            print("  条数", len(db))
            for fid, f in db.items():
                if not isinstance(f, dict):
                    continue
                rh = f.get("religious_head") or f.get("head_of_faith")
                if str(rh) == cid:
                    print("  ** 传主是该信仰之首 faith", fid,
                          json.dumps({k: v for k, v in f.items()
                                      if k in ("religious_head", "head_of_faith",
                                               "doctrine", "rite", "variables",
                                               "name", "tag")},
                                     ensure_ascii=False)[:800])
            f13 = db.get("13")
            if isinstance(f13, dict):
                print("  faith 13 键:", sorted(f13.keys()))
                for k in ("religious_head", "head_of_faith", "rite", "variables",
                          "tenet_popularity", "doctrine"):
                    if k in f13:
                        print("   faith13.%s =" % k,
                              json.dumps(f13[k], ensure_ascii=False)[:1200])
        else:
            db = obj.get("database") or obj
            print("  条数", len(db))
            for rid, r in db.items():
                if not isinstance(r, dict):
                    continue
                head = r.get("head_of_rite") or r.get("head")
                if str(head) == cid or rid in ("154", "185"):
                    print("  -- rite", rid, "head=", head, "键:", sorted(r.keys()))
                    print("    ",
                          json.dumps({k: v for k, v in r.items()
                                      if k not in ("counties",)},
                                     ensure_ascii=False)[:2000])

    print("=" * 78)
    print("[3] 会议 / 教义的全局线索")
    for n in [b'"recent_ecumenical_council"', b'"ecumenical_council_ongoing"',
              b'ec_throttled_faith', b'"investiture_council_pending"',
              b'pam_rite_quarrel', b'"activity_ecumenical_council"']:
        print("  ", n.decode(), "count", data.count(n))
        q, shown = 0, 0
        while shown < 3:
            q = data.find(n, q)
            if q < 0:
                break
            print("     at", q, "|",
                  data[max(0, q - 200):q + 260].decode("utf-8", "replace")
                  .replace("\n", " "))
            q += 1
            shown += 1
    del data
    gc.collect()


if __name__ == "__main__":
    main()
