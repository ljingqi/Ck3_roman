# v109 probe: which council seat does 洪卡特琳 hold in 洪大力's council, and its word.
#
# Cross-check of the task brief's claim that 「提管」 is the seat word
# `councillor_spymaster_celestial_family_head`, resolved by the existing council machinery
# (facts.py:15187 council_line). Streams only `council_task_manager` from the plain melt, so
# it does not pay for a full load. Read-only.
#
# Usage: & tools\py.ps1 tools\tests\v109_probe_council_seat.py

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import cache_lib as cl      # noqa: E402
import localization as L    # noqa: E402

MELT = os.path.join(ROOT, "output", "洪氏2", "data", "melt_1155_01_01.json")
OUT = os.path.join(ROOT, "logs", "v109_probe_council_seat.txt")

PLAYER = 33725392          # 洪大力
SEAT = "318776556"         # 洪卡特琳 court_data.council_task


def main():
    lines = []
    sect = cl.load_melt_section(MELT, "council_task_manager")
    act = (sect or {}).get("active") or {}
    lines.append("council_task_manager.active entries: %d" % len(act))
    e = act.get(SEAT)
    lines.append("seat %s -> %s" % (SEAT, json.dumps(e, ensure_ascii=False) if e else "ABSENT"))
    if isinstance(e, dict):
        owner = e.get("owner")
        lines.append("seat owner=%r  (洪卡特琳=67210684)  court_owner=%r (洪大力=%d)"
                     % (owner, e.get("court_owner"), PLAYER))
    table = json.load(open(os.path.join(ROOT, "data", "localization.json"),
                           encoding="utf-8")).get("table") or {}
    tasks = L.council_tasks()
    for gov in ("celestial_government", "feudal_government", ""):
        for imperial in (False, True):
            w = L.council_seat_word(table, tasks, (e or {}).get("type") or "", gov, imperial)
            lines.append("  seat word gov=%-22s imperial=%-5s -> %r" % (gov, imperial, w))
    pos = ((tasks or {}).get("tasks") or {}).get((e or {}).get("type") or "")
    lines.append("council_tasks.position for %r = %r" % ((e or {}).get("type"), pos))
    lines.append("loc[%r] = %r" % ("councillor_spymaster_celestial_family_head",
                                   table.get("councillor_spymaster_celestial_family_head")))
    text = "\n".join(lines) + "\n"
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
