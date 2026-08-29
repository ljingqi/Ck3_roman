# -*- coding: utf-8 -*-
"""研究: 鬦 是异体字还是乱码。只读。"""
import json
import sys

sys.path.insert(0, r"D:\Roman")

CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
MELT = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"

def main():
    melt = json.load(open(MELT, encoding="utf-8"))
    chars = {}
    for sec in ("living", "dead_unprunable", "dead_prunable"):
        for cid, c in (melt.get(sec) or {}).items():
            if isinstance(c, dict):
                chars.setdefault(cid, c)
    cache = json.load(open(CACHE, encoding="utf-8"))

    print("== 1) 熔件原始 first_name (鬦 相关角色) ==")
    for cid in ("67139527",):
        c = chars.get(cid) or {}
        fn = c.get("first_name") or ""
        print("  ", cid, "first_name:", repr(fn),
              "| 码位:", [hex(ord(x)) for x in fn if ord(x) > 127][:8])
    # 找鬦仁则
    for cid, c in chars.items():
        fn = c.get("first_name") or ""
        if "鬦" in fn or "仁则" in fn:
            print("  熔件:", cid, repr(fn))

    print("== 2) 鬦/豸 姓氏来源 (dynasty_house 名) ==")
    dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
    hit = 0
    for hid, e in dh.items():
        if not isinstance(e, dict):
            continue
        nm = e.get("name") or ""
        if isinstance(nm, str) and "鬦" in nm:
            print("  house", hid, repr(nm))
            hit += 1
            if hit > 5:
                break
    print("  含鬦的 house 数(截断):", hit)

    print("== 3) 缓存 house_name ==")
    for cid, rec in (cache.get("characters") or {}).items():
        hn = rec.get("house_name") or ""
        if "鬦" in hn:
            print("  ", cid, rec.get("name_zh"), "| house:", repr(hn))
            hit += 1
            if hit > 12:
                break

    print("== 4) 异体字判定: 与 鬬/鬭/鬥 的码位比较 ==")
    for ch in ("鬦", "鬬", "鬭", "鬥", "斗", "门", "門"):
        print("  %s U+%04X" % (ch, ord(ch)))

    print("== 5) GBK/UTF-8 往返检验 (乱码会往返失败或变码) ==")
    for ch in ("鬦", "鬬"):
        for enc in ("utf-8", "gbk"):
            try:
                b = ch.encode(enc)
                back = b.decode(enc)
                print("  %s [%s]: %s -> %s %s" % (ch, enc, b.hex(), repr(back),
                                                   "OK" if back == ch else "MISMATCH"))
            except Exception as e:
                print("  %s [%s]: 失败 %s" % (ch, enc, e))

    print("== 6) 本地化表与游戏字库里有没有 鬦 ==")
    import localization as L
    t = L.table()
    cnt = 0
    for k, v in t.items():
        if isinstance(v, str) and "鬦" in v:
            print("  loc:", k, "=", v[:40])
            cnt += 1
            if cnt > 5:
                break
    print("  本地化含鬦条目:", cnt)

if __name__ == "__main__":
    main()
