# -*- coding: utf-8 -*-
"""Fast read-only harness for the kinship / identity calculator (v109 dev tool).

Loads one campaign cache and exercises `Facts` kinship + chain APIs without any
melt, so relation wording can be iterated on in seconds instead of a full
`build_facts` run. Melt-dependent facts stay out of scope by design.

Usage:
    & tools\\py.ps1 tools\\tests\\v109_kin_calc.py <folder> <pid> <subject> [name…]
      subject/name may be a cid or a character name; with no extra names the
      subject's whole family is listed.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402


def _find(chars, token):
    """Resolve a cid or a character name to a list of cids."""
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


def _relations_of(f, cid):
    """Every pair relation the calculator can see for cid, as {other: [kinds]}."""
    out = {}
    for key in ("relations", "relation", "scripted_relations", "opinions"):
        tbl = f.cache.get(key)
        if isinstance(tbl, dict):
            for other, val in tbl.items():
                if str(cid) in str(other) or str(other) in (str(cid),):
                    out.setdefault(key, {})[other] = val
    return out


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    folder, pid, subject = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    names = sys.argv[4:]
    data = os.path.join(ROOT, "output", folder, "data")
    cache = json.load(open(os.path.join(data, f"player_{pid}.json"), encoding="utf-8"))
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, {}, names_path)
    chars = cache.get("characters") or {}
    sids = _find(chars, subject)
    if not sids:
        print(f"找不到主体 {subject}")
        return 1
    for sid in sids:
        rec = chars.get(str(sid)) or {}
        print(f"\n=== 主体 {rec.get('name')} cid={sid} "
              f"({'F' if F._female_rec(rec) else 'M'}) 生于 {rec.get('birth')} "
              f"卒于 {rec.get('death')} ===")
        print("   家族:", json.dumps(rec.get("family") or {}, ensure_ascii=False))
        print("   关系源:", json.dumps(_relations_of(f, sid), ensure_ascii=False)[:600])
        off = f._court_positions_of(sid)
        print("   宫廷职位(自身):", off)
        if names:
            targets = []
            for nm in names:
                targets += [(nm, c) for c in _find(chars, nm)]
        else:
            targets = []
            fam = rec.get("family") or {}
            for key in ("father", "real_father", "mother", "primary_spouse", "spouse",
                        "concubine", "child", "siblings"):
                for x in (fam.get(key) or []):
                    if isinstance(x, int):
                        nm = (chars.get(str(x)) or {}).get("name") or str(x)
                        targets.append((nm, x))
        seen = set()
        for nm, cid in targets:
            if cid == sid or cid in seen:
                continue
            seen.add(cid)
            other = chars.get(str(cid)) or {}
            key = F.kin_key(f.cache, sid, cid, spouse_back=f._spouse_back_index(),
                            rev=f._kin_rev_index())
            print(f"\n  · {nm} (cid {cid}, {'F' if F._female_rec(other) else 'M'})")
            print(f"      kin_key        = {key!r}  → {F.kin_text(key)!r}")
            print(f"      blood_words    = {f.blood_kin_words_for(cid, sid)}")
            print(f"      chain          = {f.kin_chain_words_for(cid, sid)}")
            print(f"      identity_parts = {f.identity_parts(cid, sid)}")
            print(f"      affinal        = {f.affinal_kin_words_for(cid, sid)}")
            print(f"      relation_word  = {f.relation_word_for(cid, sid)!r}")
            print(f"      court(自身宫)  = {f._court_positions_of(cid)}")
            print(f"      label(brief)   = {f.person_label(cid, None, 'brief')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
