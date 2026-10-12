# -*- coding: utf-8 -*-
"""v122: exercise the prisoner-as-subject punishment wording without touching save data.

Checks: every punishment template formats with the v122 arguments, the mutilation
outranks a plain torture on the same day, and the "折磨与" slot appears only when a
separate torture is recorded.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import facts
import style as _style

W = _style.FACT_WORDING


def ev(kind, victim, date="1084.9.30", side="torturer", owner=1):
    if side == "torturer":
        return {"type": "torturer_memory", "date": date,
                "ident": {"owner": owner, "parts": {"victim": victim},
                          "torture_kind": kind}}
    return {"type": "tortured_memory", "date": date,
            "ident": {"owner": victim, "torture_kind": kind}}


def render(pun, vn="帖行本", jn="田所普罗丢色", span="22日后", same=False):
    if pun is None:
        return "(no punishment)"
    return W[pun[0]].format(sp=W["prison_same_day"] if same else span,
                            jailer=jn, victim=vn,
                            torture=W["prison_torture_prefix"] if pun[2] else "")


def main():
    ok = True
    cases = [
        ("castrated only", [ev("castrated", 7)], 7, "prison_punish_castrated", False),
        ("blinded only", [ev("blinded", 7)], 7, "prison_punish_blinded", False),
        ("plain torture", [ev("torture", 7)], 7, "prison_punish_generic", False),
        ("beardless", [ev("castrated_beardless", 7)], 7, "prison_punish_beardless", False),
        ("castrated + torture", [ev("torture", 7), ev("castrated", 7)], 7,
         "prison_punish_castrated", True),
        ("torture first, blinded", [ev("maim_arm", 7), ev("blind", 7)], 7,
         "prison_punish_blinded", True),
        ("tortured_memory viewpoint", [ev("castrated", 7, side="tortured")], 7,
         "prison_punish_castrated", False),
        ("other day", [ev("castrated", 7, date="1085.1.1")], 7, None, False),
        ("other victim", [ev("castrated", 8)], 7, None, False),
    ]
    for name, events, victim, want_key, want_extra in cases:
        pun = facts._punishment_on(events, victim, "1084.9.30")
        got_key = pun[0] if pun else None
        got_extra = bool(pun[2]) if pun else False
        hit = (got_key == want_key and got_extra == want_extra)
        ok = ok and hit
        print(f"[{'ok' if hit else 'FAIL'}] {name}: {got_key} extra={got_extra}")
    print()
    for key in ("prison_punish_castrated", "prison_punish_blinded",
                "prison_punish_beardless", "prison_punish_generic"):
        line = render((key, 0, False))
        line2 = render((key, 0, True), same=True)
        print(key)
        print("   with span : " + line)
        print("   with tort : " + line2)
        # The jailer must be gone: no slot left for it and no "被其" left behind
        if "被其" in W[key] or "{jailer}" in W[key]:
            ok = False
            print("   FAIL: jailer still named")
    print()
    print("RESULT:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
