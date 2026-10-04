# -*- coding: utf-8 -*-
"""v103 issue-4 probe at decade 4 / as_of 1050-01-01: does 桑莎 (16895643) appear in the
wife list / former-wife list / sibling list of the protagonist profile, and what are her
wedding + death dates? Read-only."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
PID = 135480
SAN = 16895643
AS_OF = "1050.1.1"


def main():
    cache = json.load(open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8"))
    melt = cl.load_melt(os.path.join(DATA, "melt_1043_01_01.json.xz"))
    chars = cl.all_characters(melt)
    names = os.path.join(ROOT, "data", "names.json")
    facts = F.build_facts(cache, melt, names, as_of=AS_OF, decade=4)
    f = facts["_facts"]

    print("==== 桑莎 dates / status ====")
    print("  wedding_date(PID,SAN) =", repr(f.wedding_date(PID, SAN)))
    print("  spouse_end(PID,SAN)   =", f.spouse_end(PID, SAN))
    print("  _char_death_date(SAN) =", repr(f._char_death_date(SAN)))
    print("  _char_death_date(PID) =", repr(f._char_death_date(PID)))
    print("  bio_window_start      =", repr(f._bio_window_start()))
    print("  spouse_active_in_window(SAN) =", f.spouse_active_in_window(SAN))
    pfam = (cache.get("characters") or {}).get(str(PID)).get("family") or {}
    for k in ("primary_spouse", "spouse", "former_spouses", "siblings"):
        print(f"  PID.family.{k:16}", pfam.get(k))
    print("  SAN in former_spouses?", SAN in (pfam.get("former_spouses") or []))
    print("  SAN in siblings?", SAN in (pfam.get("siblings") or []))

    print("\n==== protagonist profile block (decade 4) ====")
    p = F._protagonist(f)
    for k in ("spouses", "former_spouses", "concubines", "former_concubines",
              "siblings", "father", "mother"):
        print(f"  p[{k!r}] = {p.get(k)!r}")
    print("  SAN name in spouses?", "桑莎" in (p.get("spouses") or ""))
    print("  SAN name in former_spouses?", "桑莎" in (p.get("former_spouses") or ""))
    print("  SAN name in siblings?", "桑莎" in (p.get("siblings") or ""))

    print("\n==== direct: kin_key + blood + labels at decade 4 ====")
    print("  kin_key(PID,SAN)      =", repr(F.kin_key(cache, PID, SAN,
          spouse_back=f._spouse_back_index(), rev=f._kin_rev_index())))
    print("  blood_kin_word_for    =", repr(f.blood_kin_word_for(SAN, PID)))
    print("  kin_label(SAN)        =", repr(f.kin_label(SAN)))
    print("  display_name(SAN)     =", repr(cl.display_name(cache, SAN, melt=melt, chars=chars)))


if __name__ == "__main__":
    main()
