# -*- coding: utf-8 -*-
"""v110 dev probe: the pre-existing C-pivot anomaly (崔穆/李法台, campaign 44503), isolated.

The sweep's C part replays 「错词必纠」 with the pivot as the subject: the post-processor must
rewrite a wrong kin word in `X的<错词>Y。` into the word the calculator certifies. One case showed
up in the v110 sweep log and was absent from `logs/v109/v109_kin_after_step2.json`; this probe rebuilds
the exact call with the sweep's own construction (the pivot facts, `family_ids` + the synthetic
family roster, `check_owner(..., prod=False)`) to settle whether v110 caused it.

Verdict (2026-10-07): it did not. With `git stash push -- facts.py` the same single failure
reproduces byte-identically, and the case is already present in `logs/v109/v109_kin_after_step1.json`
(therefore also in the v109 code). The pair has no common ancestor within `_DEEP_MAXD` and no blood
term at all -- `blood_kin_words_for(44717, 16795531) == []`, its only chain word is the game
relation 仇敌 -- so no route-enumeration change can reach it. The post-processor simply declines to
rewrite a word that its own chain (`X的仇敌Y`) does not confirm. The only difference between
after_step1 and after_step2 is that the step2 sweep run skipped the C part (`--no-c`).

Usage:
    & tools\\py.ps1 tools\\tests\\v110_probe_c_anomaly.py

Resolution (2026-10-07): the pair are **former spouses who are now 仇敌** (崔穆 and 李法台 are in each
other's `ever_spouses`/`former_spouses`, and the only chain word is the relation 仇敌 -- no blood
route, no `kin_word` in either direction). `_fix_kin_roles` replaces a wrong kin word only with a word
`F.kin_word` certifies, and it refuses to guess (`if len(words) != 1: continue`), so it leaves this
line alone by design. The C probe was demanding a *relation* word as the replacement target -- a
behaviour the production function documents as out of scope -- so the probe now asserts the contract
instead: relation-only pairs must stay untouched (`v108_kin_sweep.check_owner`, tag 「关系词对不改写」,
counted in the module-level REL_ONLY and reported in the C summary). Nothing in `facts.py` changed.
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "tests"))
import facts as F          # noqa: E402
import biography as B      # noqa: E402
import v108_kin_sweep as S  # noqa: E402

X, Y = 16795531, 44717
LINE = "%s的妹妹%s。" % ("崔穆", "李法台")


def main():
    data = os.path.join(ROOT, "output", "洪氏2", "data")
    cache = json.load(open(os.path.join(data, "player_44503.json"), encoding="utf-8"))
    chars = cache["characters"]
    snaps = S.find_snapshots(data)
    snap = (snaps.get(44503) or [None])[0]
    facts = S.load_facts(snap) if snap else {}
    as_of = S.as_of_of(cache, facts)
    fi = F.Facts(cache, {}, None, as_of=as_of, decade=facts.get("decade"))
    if not facts.get("characters"):
        facts["characters"] = {}
    print("快照 %s ｜ as_of=%s ｜ 事实面角色 %d"
          % (os.path.basename(snap) if snap else "无", as_of, len(facts["characters"])))
    print("名字：传主 %r 相对人 %r" % (S.name_of(chars, X), S.name_of(chars, Y)))
    fi_x, cache_x = S.pivot(fi, cache, X, {})
    fam = S.family_ids(chars, 44503, {str(k) for k in facts["characters"]})
    fam_roster = {str(x): {"name": S.name_of(chars, x)} for x in fam}
    facts_x = {"_facts": fi_x, "characters": fam_roster}
    print("家族 %d 人；事实面（C 段口径）用家族名单" % len(fam))
    print("kin_word(cache,x,y)      = %r" % F.kin_word(cache, X, Y))
    print("kin_word_for(y,x)        = %r" % fi_x.kin_word_for(Y, X))
    print("blood_kin_words_for(y,x) = %r" % fi_x.blood_kin_words_for(Y, X))
    print("kin_chain_words_for(y,x) = %r" % fi_x.kin_chain_words_for(Y, X))
    fath, moth = fi_x._parent_maps()
    print("血缘路线共同祖先 = %d"
          % len(set(fi_x._ancestor_routes(X, fath, moth, {Y}))
                  & set(fi_x._ancestor_routes(Y, fath, moth, {X}))))
    for line in (LINE, "%s的仇敌%s。" % (S.name_of(chars, X), S.name_of(chars, Y))):
        got = B._fix_kin_roles(line, facts_x, cache_x, subject_ids=[X])
        print("  %-22r → %r  %s" % (line, got, "改写" if got != line else "原样"))
    ys = set()
    fam_x = (chars.get(str(X)) or {}).get("family") or {}
    for fld in S.KIN_FIELDS:
        for y in (fam_x.get(fld) or []):
            if isinstance(y, int) and str(y) in chars:
                ys.add(y)
    n, bad, gap, unres = S.check_owner(chars, fi, cache, X, ys, fam_roster, {}, False)
    print("check_owner（C 段口径）：断言 %d / 失败 %d / 覆盖缺口 %d / 同名不可判 %d"
          % (n, len(bad), gap, unres))
    for b in bad:
        print("   ", b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
