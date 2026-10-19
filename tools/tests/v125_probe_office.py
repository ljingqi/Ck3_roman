# -*- coding: utf-8 -*-
"""v125 探针四：按实跑口径 (as_of=912.10.6) 复算「枢密使兼枢密使」与「惟仁/上皇」。只读。

用法：& tools\\py.ps1 tools\\tests\\probe_v125d.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

FOLDER, PID, AS_OF = "杨氏", 38932, "912.10.6"


def main():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache = json.load(open(os.path.join(data, f"player_{PID}.json"), encoding="utf-8"))
    melts = [x for x in os.listdir(data)
             if x.startswith("melt_") and "_idx" not in x and x.endswith(".json")]

    def _k(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)
    melt = cl.load_melt(os.path.join(data, max(melts, key=_k)))
    campaign = {}
    for fn in os.listdir(data):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        c = json.load(open(os.path.join(data, fn), encoding="utf-8"))
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(m.group(1))] = c
    facts = F.build_facts(cache, melt, os.path.join(data, "names.json"),
                          as_of=AS_OF, decade=None, campaign=campaign or None)
    f = facts["_facts"]
    out = []

    def p(*a):
        out.append(" ".join(str(x) for x in a))

    pid = cache.get("player_id")
    p("== ⑤ 杨尚昆 (16798895) 实跑口径 ==")
    sq, tz = 16798895, None
    for k, rec in (cache.get("characters") or {}).items():
        if (rec.get("name_full") or "").find("嗣之") >= 0:
            tz = int(k)
    p(" 嗣之 cid:", tz)
    p(" _court_positions_of(date=as_of):", f._court_positions_of(sq, date=AS_OF, subject=pid))
    p(" _council_seats_of:", f._council_seats_of(sq, subject=pid, date=AS_OF))
    p(" _subject_office_words:", f._subject_office_words(sq, AS_OF))
    p(" _ministry_office_at:", f._ministry_office_at(sq, f._anchor_date(sq)))
    p(" official_title:", f.official_title(sq))
    for d in (AS_OF, "878.7.25", "902.4", "904.4.7"):
        p(f"  label brief @{d}:", f.person_label(sq, date=d, style="brief"))
        p(f"  label timeline @{d}:", f.person_label(sq, date=d, style="timeline"))
    p(" identity(尚昆, 传主):", f.identity_parts(sq, pid))
    if tz:
        p(" identity(尚昆, 嗣之):", f.identity_parts(sq, tz))
        p(" identity(嗣之, 尚昆):", f.identity_parts(tz, sq))
    p(" court_roster rows for 尚昆:")
    try:
        for row in (cache.get("court_positions") or [])[-3:]:
            p("   date", row.get("date"), [x for x in (row.get("positions") or [])
                                          if x.get("employee") == sq])
    except Exception as e:                                     # noqa: BLE001
        p("   ERR", e)

    p("")
    p("== ② 惟仁/大历 (16287) ==")
    cid = 16287
    rec = (cache.get("characters") or {}).get(str(cid)) or {}
    p(" cache name:", rec.get("name"), rec.get("name_zh"), rec.get("dynasty_name"),
      "death:", json.dumps(rec.get("death"), ensure_ascii=False)[:200])
    c = f._chars.get(str(cid)) or {}
    p(" dead_data:", json.dumps(c.get("dead_data"), ensure_ascii=False)[:400])
    p(" name_with_regnal:", f.name_with_regnal(cid))
    p(" dynasty_name:", f.dynasty_name(cid), " imperial_clan_state:", f._imperial_clan_state(cid))
    p(" _tenno_prince_word:", f._tenno_prince_word(cid) or "")
    p(" _tenno_prince_name:", f._tenno_prince_name(cid) or "")
    p(" japan_top_office:", f.japan_top_office(cid) or "")
    p(" official_title:", f.official_title(cid) or "")
    p(" _char_flags(no date):", sorted(f._char_flags(cid)))
    p(" _char_flags(as_of):", sorted(f._char_flags(cid, AS_OF)))
    p(" government(as_of):", f._character_government(cid, AS_OF))
    p(" government(None):", f._character_government(cid, None))
    for d in ("892.9.28", "892.9.29", "892.10.10", "900.7.14", AS_OF):
        tier, tid = f._primary_title_at(cid, as_of=d)
        key = (f._lt.get(str(tid)) or {}).get("key") if tid is not None else None
        p(f" @{d}: tier={tier} tid={tid} key={key}",
          "| japan_top_office:", f.japan_top_office(cid, d) or "",
          "| official:", f.official_title(cid, d) or "",
          "| prince:", f._tenno_prince_word(cid, d) or "",
          "| name_regnal:", f.name_with_regnal(cid, d),
          "| label:", f.person_label(cid, date=d, style="brief"))
    p(" hold intervals:")
    for tid, iv in (f._hold_intervals(cid) or {}).items():
        key = (f._lt.get(str(tid)) or {}).get("key") or ""
        p("   ", tid, key, iv)
    p(" titles by key k_chrysanthemum_throne:", f.title_by_key("k_chrysanthemum_throne"),
      "e_japan:", f.title_by_key("e_japan"))

    txt = "\n".join(out)
    with open(os.path.join(ROOT, "logs", "v125_probe_d.txt"), "w", encoding="utf-8") as fp:
        fp.write(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
