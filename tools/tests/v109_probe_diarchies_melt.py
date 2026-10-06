# v109 probe: `diarchies` section of any one melt, for date-by-date comparison.
#
# The section sits ~90% into the stream, so streaming it from an .xz melt still decompresses
# most of the file; this is why the probe is limited to a handful of dates, and why the
# 399 MB plain-text melt is scanned in bytes instead.
#
# Usage: & tools\py.ps1 tools\tests\v109_probe_diarchies_melt.py melt_1150_01_01.json.xz [liege_id]

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import cache_lib  # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    name = sys.argv[1]
    liege = int(sys.argv[2]) if len(sys.argv) > 2 else 33725392
    path = os.path.join(DATA, name)
    if not os.path.isfile(path):
        print("missing %s" % path)
        return 1
    di = cache_lib.load_melt_section(path, "diarchies")
    db = (di or {}).get("database") or {}
    live = {k: v for k, v in db.items() if isinstance(v, dict)}
    mine = {k: v for k, v in live.items() if v.get("liege") == liege or v.get("diarch") == liege}
    print("%s: entries=%d live=%d regency-family=%d"
          % (name, len(db), len(live),
             sum(1 for v in live.values() if "regen" in str(v.get("type")))))
    print("records touching %d: %d" % (liege, len(mine)))
    for k, v in mine.items():
        print("  id %s -> %s" % (k, json.dumps(v, ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
