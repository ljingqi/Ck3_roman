# -*- coding: utf-8 -*-
"""v104 [issue 5] regression sweep: every named character's display name, legacy vs patched.

The patched `_template_of_culture` recovers a runtime culture's template through its
`name_list`, so any character of a hybrid/divergence culture can gain a patronymic. This sweep
runs `display_name` twice in one process -- once with the legacy body monkeypatched back in,
once with the production body -- and prints only the changed names.

Read-only: the cache is loaded once, the melt only through `load_melt_section` (three small
sections), so no whole-melt load and no rebuild.
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
PID = 135480
MELT = os.path.join(DATA, "melt_1077_01_01.json")
OUT = os.path.join(ROOT, "logs", "v104_name_sweep.txt")


def legacy_template_of_culture(melt, cul):
    """The pre-v104 body (no name_list / parents fallback)."""
    if melt is None or cul is None:
        return ""
    cultures = (melt.get("culture_manager") or {}).get("cultures") or {}
    e = cultures.get(str(cul)) or {}
    return e.get("culture_template") or ""


def main():
    out = []

    def p(*a):
        s = " ".join(str(x) for x in a)
        out.append(s)

    cache = json.load(open(os.path.join(DATA, "player_%d.json" % PID), encoding="utf-8"))
    mini = {"culture_manager": cl.load_melt_section(MELT, "culture_manager") or {},
            "dynasty_houses": cl.load_melt_section(MELT, "dynasty_houses") or {},
            "dynasties": cl.load_melt_section(MELT, "dynasties") or {}}
    p("characters in cache:", len(cache.get("characters") or {}))
    p("culture entries:", len((mini["culture_manager"].get("cultures") or {})))

    ch = cache.get("characters") or {}
    patched = cl._template_of_culture
    rows = []
    # Two runs over the same cache: one shared memo per run keeps the name-order/patronymic
    # inference from re-walking the same houses and sibling sets for every character.
    def sweep(tpl_fn):
        cl._template_of_culture = tpl_fn
        cl._NAME_LIST_TEMPLATE_CACHE = None
        memo = {}
        out = {}
        for cid, rec in ch.items():
            if not isinstance(rec, dict) or not rec.get("name_zh"):
                continue
            out[cid] = cl.display_name(cache, cid, melt=mini, chars=None, memo=memo)
        return out

    try:
        new_all = sweep(patched)
        cl._NAME_LIST_TEMPLATE_CACHE = None
        old_all = sweep(legacy_template_of_culture)
    finally:
        cl._template_of_culture = patched
        cl._NAME_LIST_TEMPLATE_CACHE = None
    for cid, new in new_all.items():
        old = old_all.get(cid)
        if new != old:
            rows.append((cid, (ch.get(cid) or {}).get("culture"), old, new))

    p("changed names:", len(rows))
    by_cul = {}
    for cid, cul, old, new in rows:
        by_cul.setdefault(cul, []).append((cid, old, new))
    for cul in sorted(by_cul, key=lambda x: (x is None, x)):
        lst = by_cul[cul]
        p("  culture %s: %d" % (cul, len(lst)))
        for cid, old, new in lst[:40]:
            p("     %-10s %-22s -> %s" % (cid, old, new))
        if len(lst) > 40:
            p("     … %d more" % (len(lst) - 40))

    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out[:40]))
    print("full:", OUT)


if __name__ == "__main__":
    main()
