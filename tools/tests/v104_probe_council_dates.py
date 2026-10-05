# -*- coding: utf-8 -*-
"""v104 probe 8: 大公会议的活动冷却日期 / last_hosted 日期 / 圣职区归属。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_council_dates.py <melt> [cid]
"""
import gc
import json
import lzma
import re
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


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    cid = sys.argv[2] if len(sys.argv) > 2 else CID
    data = load_bytes(path)
    print("melt", path, "bytes", len(data))

    print("=" * 78)
    print("[A] 所有 activity_ecumenical_council 冷却/日期出现处")
    pat = re.compile(rb'activity_ecumenical_council":"([0-9.]+)"')
    for m in pat.finditer(data):
        o = m.start()
        # 回溯最近的 "<id>":{"first_name": 判断是不是角色条目
        seg = data[max(0, o - 400000):o]
        hits = list(re.finditer(rb'"(\d{1,12})":\{"first_name":', seg))
        owner = hits[-1].group(1).decode() if hits else "?"
        print("  at", o, "date", m.group(1).decode(),
              "最近角色条目", owner, "|",
              data[max(0, o - 120):o + 60].decode("utf-8", "replace"))

    print("=" * 78)
    print("[B] last_hosted_activity_dates / last_open_activity_dates 的位置与宿主容器")
    for key in (b'"last_hosted_activity_dates"', b'"last_open_activity_dates"',
                b'"statistics"', b'"achievement"', b'"playable_data"',
                b'"char_vassal_history"', b'"dynamic_templates"',
                b'"clerical_region_manager"', b'"clerical_region"'):
        print("  ", key.decode(), "count", data.count(key), "first", data.find(key))

    print("=" * 78)
    print("[C] 冷却日期字段所在的角色（activity_type_cooldowns）")
    for m in re.finditer(rb'"activity_type_cooldowns":\{', data):
        o = m.end()
        end = slice_value(data, o - 1)
        seg = data[max(0, o - 400000):o]
        hits = list(re.finditer(rb'"(\d{1,12})":\{"first_name":', seg))
        owner = hits[-1].group(1).decode() if hits else "?"
        blob = data[o:end].decode("utf-8", "replace")
        if "ecumenical" in blob:
            print("  角色", owner, "->", blob[:400])

    print("=" * 78)
    print("[D] clerical_region_manager")
    k = data.find(b'"clerical_region_manager"')
    print("   at", k)
    if k >= 0:
        brace = data.find(b"{", k)
        end = slice_value(data, brace)
        print("   字节", end - brace)
        try:
            obj = json.loads(data[brace:end].decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print("   !!! ", exc)
            obj = None
        if isinstance(obj, dict):
            print("   顶层键", sorted(obj.keys()))
            db = obj.get("database") or obj
            if isinstance(db, dict):
                print("   区数", len(db))
                for rid, r in list(db.items())[:40]:
                    if isinstance(r, dict):
                        print("   ", rid, json.dumps(r, ensure_ascii=False)[:300])

    print("=" * 78)
    print("[E] 传主的圣职区关联（若 landed_titles 里有 clerical_region 指向他的辖地）")
    lt = data.find(b'"landed_titles"')
    brace = data.find(b"{", lt)
    end = slice_value(data, brace)
    lto = json.loads(data[brace:end].decode("utf-8"))
    inner = lto.get("landed_titles") or lto
    mine = []
    for tid, t in inner.items():
        if isinstance(t, dict) and str(t.get("holder")) == cid:
            mine.append((tid, t.get("key"), t.get("clerical_region"),
                         t.get("clerical_region_title"), t.get("tier")))
    print("   传主持有头衔（id,key,clerical_region,clerical_region_title,tier）:")
    for row in mine:
        print("     ", row)
    # 他的伯爵领是否落在某个 clerical_region 里
    reg = {}
    for tid, t in inner.items():
        if isinstance(t, dict) and t.get("clerical_region") is not None:
            reg[tid] = (t.get("key"), t.get("holder"), t.get("clerical_region"))
    print("   全库 clerical_region 头衔数", len(reg))
    print("   其中 holder=传主 的:", [k for k, v in reg.items() if str(v[1]) == cid])
    del data
    gc.collect()


if __name__ == "__main__":
    main()
