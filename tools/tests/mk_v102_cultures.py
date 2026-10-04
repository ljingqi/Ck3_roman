# -*- coding: utf-8 -*-
"""Build the offline culture fixture used by verify_v102.py.

`cache_lib.load_melt_section()` streams a single top-level section (seconds) instead of
loading the whole 100-125 MB melt. The culture table belongs to the game installation, not
to a playthrough, so one fixture serves the caches of every campaign.

Usage: & tools\\py.ps1 tools\\tests\\mk_v102_cultures.py
Output: tools/tests/fixtures/v102_cultures.json (UTF-8)
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

MELT = os.path.join(ROOT, "output", "洪氏2", "data", "melt_1011_01_01.json")
DEST = os.path.join(ROOT, "tools", "tests", "fixtures", "v102_cultures.json")

# Only name order, language and the template (which selects the patronymic rules) matter.
CULTURE_KEYS = ("culture_template", "name_order_convention", "language")
# The houses and dynasty of this family, so house names resolve offline.
HOUSES = ("12295", "20237")
DYNASTY = "11691"


def main():
    cm = cl.load_melt_section(MELT, "culture_manager") or {}
    cultures = cm.get("cultures") or {}
    out = {}
    for cid, e in cultures.items():
        if isinstance(e, dict):
            out[str(cid)] = {k: e[k] for k in CULTURE_KEYS if k in e}
    dh = (cl.load_melt_section(MELT, "dynasties") or {}).get("dynasty_house") or {}
    fixture = {
        "_source": "melt_1011_01_01.json culture_manager/dynasties (streamed sections)",
        "culture_manager": {"cultures": out},
        "dynasties": {
            "dynasty_house": {h: {"localized_name": (dh.get(h) or {}).get("localized_name"),
                                  "dynasty": (dh.get(h) or {}).get("dynasty")}
                              for h in HOUSES},
            "dynasties": {DYNASTY: {"localized_name": "洪"}},
        },
    }
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    with io.open(DEST, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(fixture, fp, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print("cultures=%d -> %s" % (len(out), DEST))


main()
