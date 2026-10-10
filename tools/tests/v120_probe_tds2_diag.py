# -*- coding: utf-8 -*-
"""临时取证：田所2 两问的现场诊断（整载一次熔件）。

用法：& tools\\py.ps1 tools\\tests\\tmp_probe_tds2_diag.py
"""
import io
import json
import os
import re
import sys

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402
import localization as L  # noqa: E402

DATA = os.path.join(ROOT, "output", "田所2", "data")
PID = 16801324
MELT = "melt_955_01_01.json"


def main():
    cache = json.load(io.open(os.path.join(DATA, "player_%d.json" % PID), encoding="utf-8"))
    names = os.path.join(DATA, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    campaign = {}
    for fn in os.listdir(DATA):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        c = json.load(io.open(os.path.join(DATA, fn), encoding="utf-8"))
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(m.group(1))] = c
    print("载入熔件", MELT, "…", flush=True)
    melt = cl.load_melt(os.path.join(DATA, MELT))
    facts = F.build_facts(cache, melt, names, as_of=None, decade=None,
                          campaign=campaign or None)
    f = facts["_facts"]
    pid = cache["player_id"]
    print("=== 1. 政体 / 御前会议 ===")
    print("gov:", f._character_government(pid, None))
    print("council_line:", f.council_line())
    ld = (cache["characters"][str(pid)].get("landed") or {})
    act = (melt.get("council_task_manager") or {}).get("active") or {}
    for sid in (ld.get("council") or []):
        e = act.get(str(sid)) or {}
        t = e.get("type") or ""
        chain = f.council_seat_arm_word(e, pid, None)
        print("  %-28s arm=%-8s keyguess=%-8s owner=%s" % (
            t, chain, f.council_seat_word(t), e.get("owner")))
    who = act.get("9846", {}).get("owner")
    print("chaplain_title(%s) = %r" % (who, f.chaplain_title(who, None)))
    sc = f._bishop_scope(pid, who, None)
    print("bishop scope religion=%r family=%r pillars=%s" % (
        sc.get("religion"), sc.get("religion_family"), sorted(sc.get("pillars") or [])))
    print("pick_bishop_title =", L.pick_bishop_title(f._bishop_titles, sc))
    print("=== 2. 特质履历 ===")
    for line in f.trait_history_lines(pid):
        print("  ", line)


if __name__ == "__main__":
    main()
