# -*- coding: utf-8 -*-
"""v110 dev probe: every blood route the calculator sees for one (relative, subject) pair.

Read-only, cache only (no melt). Dumps the common-ancestor signatures that
`Facts.blood_kin_words_for` builds, the word each route maps to, and which of them
survive the blood budget -- so a missing 堂/表 term can be traced to a route that is
absent, a route that maps to '' (undecidable sex), or a route that lost to the budget.

Usage:
    & tools\\py.ps1 tools\\tests\\v110_probe_routes.py <folder> <pid> <subject> <relative>
      subject / relative may be a cid or a character name.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402


def _find(chars, token):
    if token.isdigit():
        return [int(token)] if str(token) in chars else []
    out = []
    for k, rec in chars.items():
        if not k.isdigit() or not isinstance(rec, dict):
            continue
        if token in (rec.get("name"), rec.get("first_name"), rec.get("name_full"),
                     rec.get("name_zh")):
            out.append(int(k))
    return out


def _nm(chars, cid):
    rec = chars.get(str(cid)) or {}
    return "%s(%s)" % (rec.get("name") or "?", cid)


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    folder, pid, subject, relative = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    data = os.path.join(ROOT, "output", folder, "data")
    cache = json.load(open(os.path.join(data, "player_%d.json" % pid), encoding="utf-8"))
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, {}, names_path)
    chars = cache.get("characters") or {}
    for sid in _find(chars, subject):
        for cid in _find(chars, relative):
            rec_s, rec_c = chars.get(str(sid)) or {}, chars.get(str(cid)) or {}
            print("=" * 78)
            print("subject  %s  %s" % (_nm(chars, sid), "F" if F._female_rec(rec_s) else "M"))
            print("relative %s  %s" % (_nm(chars, cid), "F" if F._female_rec(rec_c) else "M"))
            print("kin_key        = %r -> %r" % (F.kin_key(
                cache, sid, cid, spouse_back=f._spouse_back_index(), rev=f._kin_rev_index()),
                f.blood_kin_word_for(cid, sid)))
            fath, moth = f._parent_maps()
            print("father_of(s)   = %s" % [ _nm(chars, x) for x in (fath.get(sid) or [])])
            print("mother_of(s)   = %s" % [ _nm(chars, x) for x in (moth.get(sid) or [])])
            print("father_of(c)   = %s" % [ _nm(chars, x) for x in (fath.get(cid) or [])])
            print("mother_of(c)   = %s" % [ _nm(chars, x) for x in (moth.get(cid) or [])])
            routes = f._ancestor_routes(sid, fath, moth, {cid})
            croutes = f._ancestor_routes(cid, fath, moth, {sid})
            common = sorted(set(routes) & set(croutes))
            print("-" * 78)
            print("common ancestors: %d" % len(common))
            cfemale = f._is_female(cid)
            for anc in common:
                ds, ms = routes[anc]
                dc, mc = croutes[anc]
                if ds == 0 and dc == 0:
                    continue
                older = F._older_rec(chars.get(str(cid)) or {}, chars.get(str(sid)) or {}, cid, sid)
                key = F._kin_key_of_route(ds, dc, ms, mc, cfemale, older)
                print("  A=%-22s up_s=%d up_c=%d ms=%-5s mc=%-5s gap=%+d -> key=%-22r word=%r"
                      % (_nm(chars, anc), ds, dc, ms, mc, ds - dc, key, F.kin_text(key)))
            print("-" * 78)
            print("blood_kin_words_for = %s" % f.blood_kin_words_for(cid, sid))
            print("（预算 %d；主词 %r）" % (f._KIN_CHAIN_BLOOD_MAX, f.blood_kin_word_for(cid, sid)))
            print("identity_parts      = %s" % f.identity_parts(cid, sid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
