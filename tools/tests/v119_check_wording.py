# -*- coding: utf-8 -*-
"""v119 check: every prison-row tail clause names its own subject.

The head is 「{jailer}囚禁{victim}」, so a subject-less tail attaches to the head's subject — the
protagonist — and 「1个月后遭阉割而获释」 read as if the jailer had been castrated (the 1232
洪希晏/朮赤 line). This check renders each tail with sample names and requires either the prisoner's
name or an explicit actor inside it:

    python tools/tests/v119_check_wording.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import facts as F   # noqa: E402
import style        # noqa: E402

W = style.FACT_WORDING
# tails appended after prison_jailed / prison_batch_seized / prison_captured_*
TAILS = ("prison_released", "prison_release_on", "prison_released_same_day",
         "prison_still_held", "prison_escaped", "prison_escape_on",
         "prison_escape_same_day", "prison_punish_castrated", "prison_punish_blinded",
         "prison_punish_beardless", "prison_punish_generic", "prison_died_executed",
         "prison_died_in_prison", "prison_died_devoured", "prison_enslaved")
SAMPLES = {"jailer": "甲", "victim": "乙", "sp": "1个月后", "span": "1个月",
           "date": "1234年1月2日", "bound": "1289.1.1", "n": 3, "y": 1, "m": 2,
           "slave": "乙", "actor": "甲", "year": "1234年", "since": "", "names": "丙、丁",
           "name": "", "strength": "强", "other": "丙", "owner": "甲"}
# 「被其」/「被甲」 hangs the act on the jailer, so the sufferer can only be the prisoner
SUFFERER_RE = re.compile(r"乙|被其|被甲|尽数|\d+人")


def _stub(kind, manner=""):
    """Minimal Facts stand-in for `Facts.prison_tail`: only the five methods it touches."""
    class Stub:
        def _feud_role_title(self, cid, date=None):
            return {1: "甲", 2: "乙"}.get(cid, "")

        def prison_exit(self, victim, jailer, entry_date):
            return {"kind": kind, "date": "1232.9.10", "manner": manner,
                    "source": "", "reason": ""}

        def date(self, d):
            return str(d)

        def _prison_bound(self):
            return "1289.1.1"

        def prison_handover_clause(self, victim, date=None):
            return ""
    return Stub()


def render_tails():
    """Real `prison_tail` output for every exit kind: the full sentence, not just the template."""
    print("\n-- prison_tail 实渲染 --")
    cases = [("released", ""), ("converted", "改信获释"), ("escape", ""),
             ("enslaved", ""), ("held", ""), ("executed", ""), ("died_in_prison", "")]
    fails = []
    for kind, manner in cases:
        tail, _k, _span = F.Facts.prison_tail(_stub(kind, manner), 2, 1, "1232.8.10")
        line = f"甲囚禁乙{tail}。"
        ok = bool(SUFFERER_RE.search(tail))
        print(f"  {'PASS' if ok else 'FAIL'} {kind:14s} {line}")
        if not ok:
            fails.append(kind)
    return fails


def main():
    fails = []
    for key in TAILS:
        tpl = W.get(key)
        if tpl is None:
            print(f"  FAIL {key} 不存在")
            fails.append(key)
            continue
        try:
            tail = tpl.format(**SAMPLES)
        except KeyError as e:
            print(f"  FAIL {key} 缺槽位 {e}")
            fails.append(key)
            continue
        line = f"甲囚禁乙{tail}。"
        ok = bool(SUFFERER_RE.search(tail))
        print(f"  {'PASS' if ok else 'FAIL'} {key:28s} {line}")
        if not ok:
            fails.append(key)

    # slot cross-check: every {victim}/{jailer}/{sp}/{span}/{date}/{bound} slot the templates use must
    # be one of the samples, so a call site that forgets to pass it fails here instead of KeyError in
    # a long facts build
    slots = set()
    for key in TAILS:
        slots |= set(re.findall(r"\{(\w+)\}", W.get(key) or ""))
    unknown = slots - set(SAMPLES)
    print(f"\n  {'PASS' if not unknown else 'FAIL'} 槽位齐全: {sorted(slots)}"
          + (f" 多出 {sorted(unknown)}" if unknown else ""))
    if unknown:
        fails.append("slots")
    fails += render_tails()
    print("\n" + ("全部通过" if not fails else f"未过 {len(fails)} 项: " + "、".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
