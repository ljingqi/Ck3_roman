# -*- coding: utf-8 -*-
"""v104 probe 15: 传主 135480 的教士傀儡（playable_data.puppets）是谁、什么头衔。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_puppet_who.py <melt> [puppeteer-cid]
"""
import gc
import json
import lzma
import re
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1056_01_01.json.xz"
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


def entry(data, cid):
    if isinstance(cid, str):
        cid = cid.encode()
    p = data.find(b'"' + cid + b'":{"first_name":')
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
    print("[1] %s 的傀儡槽（playable_data.puppets）" % cid)
    _sp, obj = entry(data, cid)
    puppets = []
    if isinstance(obj, dict):
        pd = obj.get("playable_data") or {}
        puppets = pd.get("puppets") or []
        print("   name:", obj.get("first_name"), "| playable_data.puppets =",
              json.dumps(puppets, ensure_ascii=False))
        print("   playable_data.tenets =",
              json.dumps(pd.get("tenets"), ensure_ascii=False))
        print("   alive_data.activity_data =",
              json.dumps((obj.get("alive_data") or {}).get("activity_data"),
                         ensure_ascii=False))
    for pp in puppets:
        pid = str(pp.get("character"))
        print("=" * 78)
        print("[2] 傀儡 %s（type=%s）档案" % (pid, pp.get("type")))
        _s2, o2 = entry(data, pid)
        if not isinstance(o2, dict):
            print("   条目未找到")
            continue
        print("   顶层键:", sorted(o2.keys()))
        for k in ("first_name", "birth", "nickname", "nickname_text", "rite",
                  "culture", "dynasty_house", "traits", "female"):
            if k in o2:
                print("   %s = %s" % (k, json.dumps(o2[k], ensure_ascii=False)[:200]))
        print("   dead_data =", json.dumps(o2.get("dead_data"), ensure_ascii=False)[:300])
        ld = o2.get("landed_data")
        if isinstance(ld, dict):
            keep = {k: v for k, v in ld.items()
                    if k in ("government", "domain", "realm_capital", "became_ruler_date",
                             "council", "court_positions", "laws", "election_titles")}
            print("   landed_data:", json.dumps(keep, ensure_ascii=False)[:800])
        al = o2.get("alive_data") or {}
        for k in ("variables", "activity_data", "location"):
            if k in al:
                s = json.dumps(al[k], ensure_ascii=False)
                if k == "variables":
                    # 只留含 puppeteer / council / rite 的项
                    try:
                        items = (al[k] or {}).get("list") or []
                        hits = [i for i in items
                                if "puppet" in json.dumps(i, ensure_ascii=False)]
                        print("   alive_data.variables.list 中 puppet 相关:",
                              json.dumps(hits, ensure_ascii=False)[:400])
                        flags = (al[k] or {}).get("data") or []
                        fh = [i for i in flags
                              if any(w in json.dumps(i, ensure_ascii=False)
                                     for w in ("council", "rite", "head", "pope"))]
                        print("   variables.data 相关 flag（截断）:",
                              json.dumps(fh, ensure_ascii=False)[:800])
                    except Exception as exc:  # noqa: BLE001
                        print("   ", exc)
                else:
                    print("   alive_data.%s = %s" % (k, s[:400]))
        pd = o2.get("playable_data") or {}
        print("   playable_data.tenets =",
              json.dumps(pd.get("tenets"), ensure_ascii=False)[:300])
        # 头衔
        print("=" * 78)
        print("[3] landed_titles 里傀儡持有/最近持有的头衔")
        lt = data.find(b'"landed_titles"')
        brace = data.find(b"{", lt)
        end = slice_value(data, brace)
        inner = (json.loads(data[brace:end].decode("utf-8")) or {}).get("landed_titles")
        if isinstance(inner, dict):
            for tid, t in inner.items():
                if not isinstance(t, dict):
                    continue
                if str(t.get("holder")) == pid:
                    keep = {k: v for k, v in t.items()
                            if k in ("key", "holder", "clerical_region", "landless",
                                     "tier", "title_name_data", "government",
                                     "de_jure_liege")}
                    print("   --", tid, json.dumps(keep, ensure_ascii=False)[:400])
            # 该头衔的 history 里最后几位持有人
            for tid, t in inner.items():
                if not isinstance(t, dict):
                    continue
                h = t.get("history")
                if isinstance(h, dict):
                    last = list(h.items())[-2:]
                    if any(str(v.get("holder") if isinstance(v, dict) else v) == pid
                           for _d, v in last):
                        print("   (史) ", tid, t.get("key"),
                              json.dumps(dict(last), ensure_ascii=False)[:300])
    del data
    gc.collect()


if __name__ == "__main__":
    main()
