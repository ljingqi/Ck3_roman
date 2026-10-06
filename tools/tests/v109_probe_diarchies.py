# v109 probe: read only the top-level `diarchies` section of an existing melt.
#
# load_melt_section streams a single top-level key, so this costs seconds instead of the
# minutes a full load_melt() needs, and it is the only melt read this session performs on
# every top-level section we care about. Read-only.
#
# Usage: & tools\py.ps1 tools\tests\v109_probe_diarchies.py

import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import cache_lib  # noqa: E402

MELT = os.path.join(ROOT, "output", "洪氏2", "data", "melt_1155_01_01.json")
OUT = os.path.join(ROOT, "logs", "v109_probe_diarchies.txt")

LIEGE = 33725392      # 洪大力
DIARCH = 67210684     # 洪卡特琳

# Candidate top-level sections that could carry identity data.
SECTIONS = [
    "diarchies",
    "diarchy_manager",
    "regency_manager",
    "council_task_manager",
    "character_court_manager",
    "scripted_relation_manager",
    "opinion_manager",
    "character_memory_manager",
]


def main():
    lines = []
    lines.append("melt = %s" % MELT)
    lines.append("")

    di = cache_lib.load_melt_section(MELT, "diarchies")
    if not isinstance(di, dict):
        lines.append("diarchies section: ABSENT")
        db = {}
    else:
        lines.append("diarchies top-level keys: %r" % sorted(di.keys())[:20])
        db = di.get("database") or {}
        lines.append("diarchies.database entries: %d" % len(db))

    types = collections.Counter()
    live = []
    for k, v in db.items():
        if not isinstance(v, dict):
            types["<scalar:%s>" % v] += 1
            continue
        types[v.get("type")] += 1
        live.append((k, v))
    lines.append("value-type histogram: %r" % dict(types))
    lines.append("")

    lines.append("--- records touching liege=%d (洪大力) ---" % LIEGE)
    n = 0
    for k, v in live:
        if v.get("liege") == LIEGE or v.get("diarch") == LIEGE:
            lines.append("diarchy id %s -> %s" % (k, json.dumps(v, ensure_ascii=False)))
            n += 1
    lines.append("count = %d" % n)
    lines.append("")

    lines.append("--- records touching diarch=%d (洪卡特琳) ---" % DIARCH)
    n = 0
    for k, v in live:
        if v.get("liege") == DIARCH or v.get("diarch") == DIARCH:
            lines.append("diarchy id %s -> %s" % (k, json.dumps(v, ensure_ascii=False)))
            n += 1
    lines.append("count = %d" % n)
    lines.append("")

    # The record pairing the two, if any.
    lines.append("--- records pairing %d (liege) with %d (diarch) ---" % (LIEGE, DIARCH))
    n = 0
    for k, v in live:
        if v.get("liege") == LIEGE and v.get("diarch") == DIARCH:
            lines.append("diarchy id %s -> %s" % (k, json.dumps(v, ensure_ascii=False)))
            n += 1
    lines.append("count = %d" % n)
    lines.append("")

    # How many regencies are active in this melt at all (sanity for scale).
    reg = [(k, v) for k, v in live if "regen" in str(v.get("type"))]
    lines.append("regency-family records: %d of %d live records" % (len(reg), len(live)))
    lines.append("")

    lines.append("--- presence of other candidate top-level sections ---")
    for s in SECTIONS:
        try:
            got = cache_lib.load_melt_section(MELT, s)
        except Exception as exc:                       # pragma: no cover - probe only
            lines.append("%-28s ERROR %r" % (s, exc))
            continue
        if got is None:
            lines.append("%-28s ABSENT" % s)
        elif isinstance(got, dict):
            lines.append("%-28s dict, keys=%r" % (s, sorted(got.keys())[:12]))
        else:
            lines.append("%-28s %s" % (s, type(got).__name__))

    text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(text)
    print("wrote %s (%d chars)" % (OUT, len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
