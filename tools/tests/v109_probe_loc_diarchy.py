# v109 probe: what the project's own localization table makes of the diarchy type keys.
#
# data/localization.json is the table the fact layer renders through, so a landing plan for
# "摄政" has to know whether the type key is present and whether its Chinese value is a
# plain word or a nested [reference|E] that needs a second lookup. Read-only.
#
# Usage: & tools\py.ps1 tools\tests\v109_probe_loc_diarchy.py

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOC = os.path.join(ROOT, "data", "localization.json")

KEYS = [
    "temporary_regency_diarchy_type", "regency_diarchy_type",
    "nomad_regency_diarchy_type", "vizierate_diarchy_type",
    "co_monarchy_diarchy_type", "grand_secretariat_diarchy_type",
    "junior_emperorship_diarchy_type", "co_emperorship_diarchy_type",
    "temporary_regency_diarch_title", "regency_diarch_title",
    "game_concept_regent", "game_concept_regency",
    "game_concept_entrenched_regent", "game_concept_entrenched_regency",
    "game_concept_diarch", "game_concept_diarchy",
    "fill_coffers", "swell_armies", "promote_authority",
    "game_concept_mandate", "scales_of_power",
]


def main():
    with open(LOC, encoding="utf-8") as fp:
        data = json.load(fp)
    table = data.get("table") or {}
    print("localization table: %d keys, schema=%r" % (len(table), data.get("schema")))
    for k in KEYS:
        print("  %-36s %r" % (k, table.get(k)))
    # Which diarchy type keys exist at all?
    have = sorted(k for k in table if k.endswith("_diarchy_type"))
    print("all *_diarchy_type keys in table (%d): %r" % (len(have), have))
    have2 = sorted(k for k in table if k.endswith("_diarch_title"))
    print("all *_diarch_title keys in table (%d): %r" % (len(have2), have2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
