# v109 probe: does the project already hold the council-seat arm that yields 「提管」?
#
# data/council_names.json is built from the game's `name = { first_valid = { triggered_desc } }`
# chains, so this checks whether the family-head arm is already on disk (a data-only fix) or
# whether the arm conditions are not evaluated at all (a code fix). Read-only.
#
# Usage: & tools\py.ps1 tools\tests\v109_probe_council_arms.py

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "logs", "v109_probe_council_arms.txt")


def main():
    cn = json.load(open(os.path.join(ROOT, "data", "council_names.json"), encoding="utf-8"))
    table = json.load(open(os.path.join(ROOT, "data", "localization.json"),
                           encoding="utf-8")).get("table") or {}
    arms = ((cn.get("positions") or {}).get("councillor_spymaster") or [])
    lines = ["council_names.json schema=%r positions=%d"
             % (cn.get("schema"), len(cn.get("positions") or {})),
             "councillor_spymaster arms: %d" % len(arms)]
    for i, a in enumerate(arms):
        lines.append("  [%d] desc=%-52s loc=%-8r when=%s"
                     % (i, a.get("desc"), table.get(a.get("desc") or ""),
                        json.dumps(a.get("when"), ensure_ascii=False)))
    lines.append("")
    for k in ("councillor_spymaster_celestial_government_imperial",
              "councillor_spymaster_non_celestial_government_imperial",
              "councillor_spymaster_celestial_government_non_imperial",
              "councillor_spymaster_celestial_family_head",
              "councillor_spymaster"):
        lines.append("  loc[%-56s] = %r" % (k, table.get(k)))
    text = "\n".join(lines) + "\n"
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
