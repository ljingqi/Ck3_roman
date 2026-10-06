# v109 probe: resolve the diarchy type keys through the project's own localization API.
#
# Confirms that a landing plan can turn a save-side type key (`temporary_regency`) into a
# Chinese word using only the existing data/localization.json, with no re-melt. Read-only.
#
# Usage: & tools\py.ps1 tools\tests\v109_probe_loc_render.py

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import localization as L  # noqa: E402

LOC = os.path.join(ROOT, "data", "localization.json")

TYPE_KEYS = [
    "temporary_regency_diarchy_type", "regency_diarchy_type",
    "nomad_regency_diarchy_type", "vizierate_diarchy_type",
    "co_monarchy_diarchy_type", "grand_secretariat_diarchy_type",
    "junior_emperorship_diarchy_type", "co_emperorship_diarchy_type",
]
TITLE_KEYS = [k.replace("_diarchy_type", "_diarch_title") for k in TYPE_KEYS]


def main():
    table = json.load(open(LOC, encoding="utf-8")).get("table") or {}
    print("--- clean_loc_value(<type>_diarchy_type) ---")
    for k in TYPE_KEYS:
        raw = table.get(k, "")
        print("  %-34s raw=%-34r clean=%r" % (k, raw, L.clean_loc_value(raw, table)))
    print("--- clean_loc_value(<type>_diarch_title) ---")
    for k in TITLE_KEYS:
        raw = table.get(k, "")
        print("  %-34s raw=%-34r clean=%r" % (k, raw, L.clean_loc_value(raw, table)))
    print("--- mandate / scales-of-power candidate keys ---")
    for sub in ("coffers", "swell_armies", "promote_authority", "mandate", "scales_of_power"):
        hits = sorted(k for k in table if sub in k)[:14]
        print("  %-18s %r" % (sub, hits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
