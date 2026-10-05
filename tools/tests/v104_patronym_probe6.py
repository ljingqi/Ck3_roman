# -*- coding: utf-8 -*-
"""v104 probe 6: is the house branch's early return what blocks the language fallback?

In-memory only, production code untouched.
"""
import io
import json
import sys

sys.path.insert(0, r"D:\Roman")
import cache_lib as cl  # noqa: E402

OUT = r"D:\Roman\logs\v104_patronym_probe6.txt"
out = io.StringIO()


def p(*a):
    print(*a, file=out)


MELT = {"culture_manager": {"cultures": {
    "161": {"culture_template": "norse", "name_list": "name_list_norse",
            "language": "language_norse", "name_order_convention": ""},
    "75": {"culture_template": "irish", "name_list": "name_list_irish",
           "language": "language_goidelic", "name_order_convention": ""},
    "76": {"culture_template": "gaelic", "name_list": "name_list_gaelic",
           "language": "language_goidelic", "name_order_convention": ""},
    "271": {"name": "希柏耳尼亚-诺斯",
            "name_list": ["name_list_norse", "name_list_irish"],
            "language": "language_goidelic", "name_order_convention": "",
            "parents": [161, 75]},
}}}


def run(with_house, with_languages, label):
    son = {"name_zh": "耀国", "culture": 271, "dynasty_house": 20237,
           "house_name": "洪堡", "dynasty_name": "洪",
           "family": {"father": [135480], "child": []}}
    if with_languages:
        son["languages"] = ["language_goidelic"]
    if not with_house:
        son["dynasty_house"] = None
        son.pop("culture")
    cache = {"characters": {"117484775": son,
                            "135480": {"name_zh": "耀国", "culture": 271,
                                       "dynasty_house": 20237,
                                       "house_name": "洪堡",
                                       "family": {"father": [16878235],
                                                  "child": [117484775]}}}}
    chars = {"117484775": {"first_name": "耀国", "culture": 271,
                           "family_data": {},
                           "alive_data": {"languages": ["language_goidelic"]}},
             "135480": {"first_name": "耀国", "culture": 271,
                        "family_data": {"child": [117484775]}}}
    memo = {}
    tpl = cl._culture_template_of(cache, 117484775, MELT, chars=chars, memo=memo)
    ptn = cl._patronym_of(cache, 117484775, MELT, None, chars=chars, memo=memo)
    name = cl.display_name(cache, 117484775, melt=MELT, chars=chars, memo={})
    p(f"  {label}: template={tpl!r} patronym={ptn!r} display_name={name!r}")


p("=== the son, with the real cache fields ===")
run(True, True, "house set + languages set (real case)")
run(True, False, "house set, no languages")
run(False, True, "NO house, languages set")
run(False, False, "NO house, no languages")

p()
p("=== reference: the engine's own rendering of the father is 耀国·缯松 ===")
p("  (melt_1077_01_01.json byte 229083503, c_mayo timed_modifier desc)")

with open(OUT, "w", encoding="utf-8") as fp:
    fp.write(out.getvalue())
sys.stderr.write(f"written {OUT}\n")
