# -*- coding: utf-8 -*-
"""v104 probe: 在熔件里找「主持会议的教士（傀儡）」与「会议地点」的痕迹。

只做字节扫描：整读解压后的字节串（300MB+），只对切片 json.loads。
用法: & tools\\py.ps1 tools\\tests\\v104_probe_puppet_activity.py <melt 路径> [cid]
"""
import json
import lzma
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"
DEFAULT_CID = "135480"

# 顶层 / 容器级线索
TOPKEYS = [b'"characters"', b'"activity_manager"', b'"activities"', b'"landed_titles"',
           b'"situation_manager"', b'"puppets"', b'"scripted_relations"']
# 角色页内线索：傀儡链
CHAR_NEEDLES = [b'"puppeteer"', b'"puppets"', b'"puppeteers"', b'theological_agent_puppet',
                b'"puppet"', b'"puppet_type"', b'"scripted_relations"', b'"relations"',
                b'"opinion"', b'"memories"']
# 活动页内线索
ACT_NEEDLES = [b'ecumenical_council', b'"location"', b'"host"', b'"type"',
               b'"active_start_date"', b'"creation_date"', b'"variables"']


def load_bytes(path):
    if path.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()


def slice_value(data, start):
    """start = 值起始（{ 或 [ 或 " 或数字）的位置，返回该值的结束下标（不含）。"""
    ch0 = data[start:start + 1]
    if ch0 == b'"':
        i = start + 1
        esc = False
        while i < len(data):
            c = data[i:i + 1]
            if esc:
                esc = False
            elif c == b"\\":
                esc = True
            elif c == b'"':
                return i + 1
            i += 1
        return len(data)
    if ch0 not in (b"{", b"["):
        i = start
        while i < len(data) and data[i:i + 1] not in (b",", b"}", b"]"):
            i += 1
        return i
    depth = 0
    i = start
    in_str = False
    esc = False
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


def slice_member(data, off):
    """给定「键」的起始引号位置，返回 (键名, 值的切片 bytes, 值起始下标)。"""
    kend = slice_value(data, off)
    key = data[off + 1:kend - 1].decode("utf-8", "replace")
    colon = data.find(b":", kend)
    vstart = colon + 1
    while data[vstart:vstart + 1] in (b" ", b"\n", b"\t", b"\r"):
        vstart += 1
    vend = slice_value(data, vstart)
    return key, data[vstart:vend], vstart


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    cid = (sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CID).encode("utf-8")
    data = load_bytes(path)
    print("melt", path)
    print("decompressed bytes", len(data))

    print("=" * 72)
    print("[0] 顶层容器出现位置")
    for k in TOPKEYS:
        print("   ", k.decode(), "at", data.find(k), "count", data.count(k))

    # ---------------------------------------------------------------- 角色页
    print("=" * 72)
    print("[1] 角色 %s" % cid.decode())
    ck = data.find(b'"characters"')
    print("    \"characters\" at", ck)
    needle = b'"' + cid + b'":'
    ch_off = -1
    if ck >= 0:
        brace = data.find(b"{", ck)
        ch_off = data.find(needle, brace)
        print("    在 characters 容器内找", needle.decode(), "->", ch_off)
        if ch_off < 0:
            # 容器可能再嵌一层
            ch_off = data.find(needle, ck)
            print("    退化为全局首次出现 ->", ch_off)
    if ch_off >= 0:
        kend = slice_value(data, ch_off)
        colon = data.find(b":", kend)
        vstart = colon + 1
        while data[vstart:vstart + 1] in (b" ", b"\n", b"\t", b"\r"):
            vstart += 1
        vend = slice_value(data, vstart)
        blob = data[vstart:vend]
        print("    角色对象字节", len(blob))
        try:
            obj = json.loads(blob.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print("    !!! json.loads 失败", exc)
            obj = None
        if isinstance(obj, dict):
            print("    顶层键:", sorted(obj.keys()))
            for n in CHAR_NEEDLES:
                for key in obj:
                    if n.decode().strip('"') in key:
                        print("     >", key, "=",
                              json.dumps(obj[key], ensure_ascii=False)[:900])
        # 原始字节里的傀儡线索
        for n in CHAR_NEEDLES:
            c = blob.count(n)
            print("    页内", n.decode(), "count", c)

    # ---------------------------------------------------------------- 活动
    print("=" * 72)
    print("[2] activity_manager")
    am = data.find(b'"activity_manager"')
    print("    at", am)
    if am >= 0:
        brace = data.find(b"{", am)
        end = slice_value(data, brace)
        blob = data[brace:end]
        print("    activity_manager 字节", len(blob))
        try:
            obj = json.loads(blob.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print("    !!! json.loads 失败", exc)
            obj = None
        if isinstance(obj, dict):
            print("    键:", sorted(obj.keys())[:20])
            db = obj.get("database")
            if isinstance(db, dict):
                print("    database 条数", len(db))
                types = {}
                for aid, act in db.items():
                    if not isinstance(act, dict):
                        continue
                    t = str(act.get("type") or "?")
                    types[t] = types.get(t, 0) + 1
                print("    活动类型分布:",
                      json.dumps(types, ensure_ascii=False, sort_keys=True))
                for aid, act in db.items():
                    if not isinstance(act, dict):
                        continue
                    if "ecumenical" in str(act.get("type") or ""):
                        print("    --", aid,
                              json.dumps(act, ensure_ascii=False)[:2500])
                # 任取一条完整活动对象看键集
                for aid, act in list(db.items())[:2]:
                    if isinstance(act, dict):
                        print("    [样例]", aid, "键:",
                              json.dumps(sorted(act.keys()), ensure_ascii=False))
        else:
            print("    原始片段:", blob[:400].decode("utf-8", "replace"))

    # ---------------------------------------------------------------- 全局词频
    print("=" * 72)
    print("[3] 全局词频（整份熔件）")
    for n in [b'activity_ecumenical_council', b'ecumenical_council',
              b'theological_agent_puppet', b'"puppeteers"', b'"puppeteer"',
              b'catalyst_secular_hosted_ecumenical_council', b'"activities"']:
        print("   ", n.decode(), data.count(n))


if __name__ == "__main__":
    main()
