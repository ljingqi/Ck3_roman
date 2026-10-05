# -*- coding: utf-8 -*-
"""v104 probe 5: exact record slices + a minimal functional reproduction.

1. Extract the son's whole character record from the melt by brace matching and list
   its own top-level keys (does the save carry a patronymic or a `languages` field?).
2. Confirm the father's `child` list carries the son (the only parent link in the save).
3. Byte-scan the campaign CACHE (output/洪氏2/data/player_135480.json) for the son's
   record and read his `family` / `culture` / `name_full`.
4. Rebuild a minimal cache+melt from those verified values and call the real
   cache_lib functions, then simulate the proposed fix (name_list -> template).
Read-only: no production file is touched.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, r"D:\Roman")
import cache_lib as cl  # noqa: E402

MELT = r"D:\Roman\output\洪氏2\data\melt_1077_01_01.json"
CACHE = r"D:\Roman\output\洪氏2\data\player_135480.json"
OUT = r"D:\Roman\logs\v104_patronym_probe5.txt"
SON = 117484775
FATHER = 135480
GRANDFATHER = 16878235

out = io.StringIO()


def p(*a):
    print(*a, file=out)


def slice_record(path, off, limit=4_000_000):
    """The whole JSON object starting at `off` (brace matching, string aware)."""
    with open(path, "rb") as fp:
        fp.seek(off)
        buf = fp.read(limit)
    depth = 0
    in_str = False
    esc = False
    for i, b in enumerate(buf):
        if in_str:
            if esc:
                esc = False
            elif b == 0x5C:
                esc = True
            elif b == 0x22:
                in_str = False
            continue
        if b == 0x22:
            in_str = True
        elif b == 0x7B:
            depth += 1
        elif b == 0x7D:
            depth -= 1
            if depth == 0:
                return buf[:i + 1]
    return buf


def offsets_of(path, needle, cap=20):
    res = []
    with open(path, "rb") as fp:
        off = 0
        tail = b""
        CH = 8 * 1024 * 1024
        while True:
            buf = fp.read(CH)
            if not buf:
                break
            data = tail + buf
            base = off - len(tail)
            s = 0
            while True:
                k = data.find(needle, s)
                if k < 0:
                    break
                res.append(base + k)
                if len(res) >= cap:
                    return res
                s = k + 1
            tail = data[-len(needle) - 8:]
            off += len(buf)
    return res


def main():
    # ---- 1) the son's own record -------------------------------------------
    holds = offsets_of(MELT, b'"117484775":{"first_name"', cap=4)
    p("=== 1) son record ===")
    p("  record starts:", holds)
    son_blob = slice_record(MELT, holds[0] + len(b'"117484775":'))
    son = json.loads(son_blob.decode("utf-8"))
    p("  bytes:", len(son_blob))
    p("  top-level keys:", sorted(son.keys()))
    p("  first_name:", son.get("first_name"), "| culture:", son.get("culture"),
      "| house:", son.get("dynasty_house"))
    p("  family_data:", son.get("family_data"))
    p("  any patronym-ish key:",
      [k for k in son if "patron" in k.lower() or "father" in k.lower()])
    ad = son.get("alive_data") or {}
    p("  alive_data keys:", sorted(ad.keys())[:20])
    p("  alive_data.languages:", ad.get("languages"))
    p("  death/dead_data:", son.get("dead_data"))

    # ---- 2) the father's own record ---------------------------------------
    fh = offsets_of(MELT, b'"135480":{"first_name"', cap=4)
    p()
    p("=== 2) father record ===")
    p("  record starts:", fh)
    f_blob = slice_record(MELT, fh[0] + len(b'"135480":'))
    f = json.loads(f_blob.decode("utf-8"))
    p("  bytes:", len(f_blob))
    p("  keys:", sorted(f.keys()))
    p("  first_name:", f.get("first_name"), "| culture:", f.get("culture"),
      "| dead_data.culture:", (f.get("dead_data") or {}).get("culture"))
    p("  family_data.father:", (f.get("family_data") or {}).get("father"))
    p("  family_data.child contains son:",
      SON in ((f.get("family_data") or {}).get("child") or []))
    p("  grandfather record exists:",
      len(offsets_of(MELT, b'"16878235":{"first_name"', cap=1)) > 0)

    # ---- 3) the cache's view of the son -----------------------------------
    p()
    p("=== 3) cache record ===")
    ch = offsets_of(CACHE, b'"117484775":{"name_zh"', cap=3) \
        or offsets_of(CACHE, b'"117484775":{"', cap=3)
    p("  cache hits:", ch)
    if ch:
        blob = slice_record(CACHE, ch[0] + len(b'"117484775":'), limit=200_000)
        try:
            rec = json.loads(blob.decode("utf-8"))
        except Exception as e:                                 # noqa: BLE001
            rec = None
            p("  parse failed:", e, blob[:400])
        if rec:
            p("  keys:", sorted(rec.keys()))
            for k in ("name_zh", "name_full", "house_name", "dynasty_name",
                      "dynasty_house", "culture", "culture_history", "family",
                      "languages"):
                p(f"  {k}: {rec.get(k)!r}")

    # ---- 4) minimal functional reproduction --------------------------------
    p()
    p("=== 4) cache_lib functional reproduction ===")
    mini_melt = {
        "culture_manager": {"cultures": {
            "161": {"culture_template": "norse", "name_list": "name_list_norse",
                    "language": "language_norse", "name_order_convention": ""},
            "75": {"culture_template": "irish", "name_list": "name_list_irish",
                   "language": "language_goidelic", "name_order_convention": ""},
            "76": {"culture_template": "gaelic", "name_list": "name_list_gaelic",
                   "language": "language_goidelic", "name_order_convention": ""},
            # hybrid: no culture_template, name_list as the merged duplicate keys
            "271": {"name": "希柏耳尼亚-诺斯", "name_list": ["name_list_norse",
                                                            "name_list_irish"],
                    "language": "language_goidelic", "name_order_convention": "",
                    "parents": [161, 75]},
        }},
        "dynasty_houses": {"20237": {"localized_name": "洪堡",
                                     "dynasty": 11691}},
        "dynasties": {"11691": {"name": "dynn_Hongbao"}},
    }
    mini_cache = {"characters": {
        str(SON): {"name_zh": "耀国", "name_full": "耀国·洪堡", "culture": 271,
                   "dynasty_house": 20237, "house_name": "洪堡",
                   "dynasty_name": "洪堡",
                   "family": {"father": [FATHER], "child": [],
                              "primary_spouse": [154984]}},
        str(FATHER): {"name_zh": "耀国", "culture": 271, "dynasty_house": 20237,
                      "house_name": "洪堡", "dynasty_name": "洪堡",
                      "family": {"father": [GRANDFATHER], "child": [SON]}},
        str(GRANDFATHER): {"name_zh": "缯", "culture": 271,
                           "dynasty_house": 20237, "house_name": "洪堡",
                           "family": {"child": [FATHER]}},
    }}
    chars = {str(SON): {"first_name": "耀国", "culture": 271, "family_data": {}},
             str(FATHER): {"first_name": "耀国", "culture": 271,
                           "family_data": {"child": [SON]}},
             str(GRANDFATHER): {"first_name": "缯", "culture": 271,
                                "family_data": {"child": [FATHER]}}}
    for cid, who in ((SON, "son"), (FATHER, "father"), (GRANDFATHER, "grandfather")):
        memo = {}
        tpl = cl._culture_template_of(mini_cache, cid, mini_melt, chars=chars,
                                      memo=memo)
        ptn = cl._patronym_of(mini_cache, cid, mini_melt, None, chars=chars,
                              memo=memo)
        order = cl.resolved_name_order(mini_cache, cid, melt=mini_melt,
                                       chars=chars, memo=memo)
        name = cl.display_name(mini_cache, cid, melt=mini_melt, chars=chars,
                              memo={})
        p(f"  {who} {cid}: template={tpl!r} patronym={ptn!r} order={order!r} "
          f"display_name={name!r}")
    p("  culture 271 entry as the project would merge it:",
      json.dumps(mini_melt["culture_manager"]["cultures"]["271"],
                 ensure_ascii=False))

    # ---- 5) the proposed fix, simulated in-memory only ---------------------
    p()
    p("=== 5) simulated fix: name_list -> template ===")
    name_list_to_tpl = {"name_list_norse": "norse", "name_list_irish": "irish",
                        "name_list_gaelic": "gaelic"}
    orig = cl._template_of_culture

    def patched(melt, cul):
        t = orig(melt, cul)
        if t:
            return t
        e = ((melt or {}).get("culture_manager") or {}).get("cultures", {}).get(str(cul)) or {}
        nl = e.get("name_list")
        for one in (nl if isinstance(nl, list) else [nl]):
            if one in name_list_to_tpl:
                return name_list_to_tpl[one]
        for par in (e.get("parents") or []):
            t2 = orig(melt, par)
            if t2:
                return t2
        return ""

    cl._template_of_culture = patched
    try:
        for cid, who in ((SON, "son"), (FATHER, "father"), (GRANDFATHER, "grandfather")):
            memo = {}
            tpl = cl._culture_template_of(mini_cache, cid, mini_melt, chars=chars,
                                          memo=memo)
            ptn = cl._patronym_of(mini_cache, cid, mini_melt, None, chars=chars,
                                  memo=memo)
            name = cl.display_name(mini_cache, cid, melt=mini_melt, chars=chars,
                                   memo={})
            p(f"  {who} {cid}: template={tpl!r} patronym={ptn!r} display_name={name!r}")
    finally:
        cl._template_of_culture = orig
    return 0


if __name__ == "__main__":
    main()
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(out.getvalue())
    sys.stderr.write(f"written {OUT}\n")
