# -*- coding: utf-8 -*-
"""v104 [issue 5] verify: does the patched `_template_of_culture` give the engine's patronymic?

Uses the **production** functions on the real culture table (sliced out of the melt) plus a
minimal cache holding the three characters, so no 244 MB cache load is needed.

Asserts: son -> 耀国·耀国松, father -> 耀国·缯松 (the string the engine itself wrote into the
save), grandfather -> 缯·洪堡 (no father, unchanged).
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cache_lib as cl  # noqa: E402

MELT = os.path.join(ROOT, "output", "洪氏2", "data", "melt_1077_01_01.json")
OUT = os.path.join(ROOT, "logs", "v104_verify_names.txt")
SON, FATHER, GRANDFATHER = 117484775, 135480, 16878235


def culture_slice(path):
    """The `culture_manager` value of a melt, through the project's section loader.

    A plain json.loads would keep only the *last* of the duplicate `name_list` keys and so see
    `name_list_irish` alone; `load_melt_section` applies the same `object_pairs_hook` as
    `load_melt`, i.e. `["name_list_norse", "name_list_irish"]`."""
    return cl.load_melt_section(path, "culture_manager") or {}


def main():
    lines = []

    def p(*a):
        s = " ".join(str(x) for x in a)
        lines.append(s)
        print(s)

    cm = culture_slice(MELT)
    cults = cm.get("cultures") or {}
    c271 = cults.get("271") or {}
    p("culture 271 raw:", json.dumps({k: c271.get(k) for k in
                                      ("name", "name_list", "parents", "culture_template",
                                       "name_order_convention")}, ensure_ascii=False))
    fail = 0

    # The melt handed to the name functions carries the real culture table plus the minimal
    # house/dynasty rows the west-surname branch needs.
    mini_melt = {
        "culture_manager": {"cultures": {k: v for k, v in cults.items()
                                         if k in ("271", "161", "75", "265")}},
        "dynasty_houses": {"20237": {"localized_name": "洪堡", "dynasty": 11691}},
        "dynasties": {"11691": {"name": "dynn_Hongbao"}},
    }
    mini_cache = {"characters": {
        str(SON): {"name_zh": "耀国", "name_full": "耀国·洪堡", "culture": 271,
                   "dynasty_house": 20237, "house_name": "洪堡", "dynasty_name": "洪堡",
                   "family": {"father": [FATHER], "child": []}},
        str(FATHER): {"name_zh": "耀国", "name_full": "耀国·洪堡", "culture": 271,
                      "dynasty_house": 20237, "house_name": "洪堡", "dynasty_name": "洪堡",
                      "family": {"father": [GRANDFATHER], "child": [SON]}},
        str(GRANDFATHER): {"name_zh": "缯", "culture": 271, "dynasty_house": 20237,
                           "house_name": "洪堡", "dynasty_name": "洪堡",
                           "family": {"child": [FATHER]}},
    }}
    chars = {str(SON): {"first_name": "耀国", "culture": 271, "family_data": {}},
             str(FATHER): {"first_name": "耀国", "culture": 271,
                           "family_data": {"child": [SON]}},
             str(GRANDFATHER): {"first_name": "缯", "culture": 271,
                                "family_data": {"child": [FATHER]}}}

    want = {SON: "耀国·耀国松", FATHER: "耀国·缯松", GRANDFATHER: "缯·洪堡"}
    for cid, who in ((SON, "son"), (FATHER, "father"), (GRANDFATHER, "grandfather")):
        memo = {}
        tpl = cl._culture_template_of(mini_cache, cid, mini_melt, chars=chars, memo=memo)
        ptn = cl._patronym_of(mini_cache, cid, mini_melt, None, chars=chars, memo=memo)
        name = cl.display_name(mini_cache, cid, melt=mini_melt, chars=chars, memo={})
        ok = name == want[cid]
        fail += 0 if ok else 1
        p(f"[{'PASS' if ok else 'FAIL'}] {who} {cid}: template={tpl!r} patronym={ptn!r} "
          f"display_name={name!r} want={want[cid]!r}")

    p("failures:", fail)
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
