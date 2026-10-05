# -*- coding: utf-8 -*-
"""v104 probe: dump the church situation history rows from the melt by byte scanning.

No json.loads of the whole melt (300MB+); we locate the situation and slice its history array,
then json.loads only that slice.
"""
import json
import sys

MELT = r"D:\Roman\output\洪氏2\data\melt_1077_01_01.json"
KINDS = ("catalyst_hosted_ecumenical_council",
         "catalyst_secular_hosted_ecumenical_council",
         "catalyst_the_christian_church_papal_bull_enacted",
         "catalyst_pope_declared_popular_core_tenet",
         "catalyst_pope_declared_unpopular_core_tenet",
         "catalyst_heresy_light_outbreak")


def slice_value(data, start):
    """Given index of a value start ({ or [), return the slice text of that value."""
    depth = 0
    i = start
    in_str = False
    esc = False
    while i < len(data):
        ch = data[i:i + 1]
        if in_str:
            if esc:
                esc = False
            elif ch == b"\\":
                esc = True
            elif ch == b'"':
                in_str = False
        else:
            if ch == b'"':
                in_str = True
            elif ch in (b"{", b"["):
                depth += 1
            elif ch in (b"}", b"]"):
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return len(data)


def main():
    m = MELT if len(sys.argv) < 2 else sys.argv[1]
    with open(m, "rb") as f:
        data = f.read()
    print("melt", m, "size", len(data))
    k = data.find(b'"situation_manager"')
    print("situation_manager at", k)
    if k < 0:
        return
    j = data.find(b"{", k)
    end = slice_value(data, j)
    blob = data[j:end]
    print("situation_manager bytes", len(blob))
    sub = json.loads(blob.decode("utf-8"))
    db = sub.get("database") or {}
    for sid, s in db.items():
        if not isinstance(s, dict):
            continue
        print("--", sid, "type", s.get("type"), "rows", len(s.get("history") or []),
              "keys", sorted(s.keys()))
        for h in (s.get("history") or []):
            c = h.get("catalyst") if isinstance(h, dict) else None
            if not isinstance(c, dict):
                continue
            if str(c.get("catalyst") or "") in KINDS and str(c.get("date") or "") >= "1010":
                print("   ", json.dumps(c, ensure_ascii=False))
        for key in ("participants", "activities", "variables", "manual_participant_candidates",
                    "sub_region_refs", "start_date", "is_valid_custom"):
            if key in s:
                v = s[key]
                print("   ", key, json.dumps(v, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()
