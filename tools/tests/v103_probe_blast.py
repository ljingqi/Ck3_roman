# -*- coding: utf-8 -*-
"""v103 Issue-2 blast radius: list every character whose name order the new
maternal-Eastern rule flips (own culture undecidable, mother's side Eastern, but the
paternal personal culture alone would have said Western). Read-only."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
PID = 135480


def main():
    cache = json.load(open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8"))
    melt = cl.load_melt(os.path.join(DATA, "melt_999_01_01.json.xz"))
    chars = cl.all_characters(melt)
    cultures = ((melt.get("culture_manager") or {}).get("cultures") or {})
    ch = cache.get("characters") or {}

    flipped = []
    memo = {}
    for cid, rec in ch.items():
        if not rec.get("name_zh"):
            continue
        # own culture decidable? (step 1) -> unaffected by the new rule
        cul = cl._culture_id_at_rec(rec, None)
        if cul is None:
            cul = rec.get("culture")
        if cul is not None:
            continue
        ho = cl._house_name_order(cache, rec, melt, memo=memo)
        if ho not in cl.EASTERN_NAME_ORDERS:
            continue
        pa = cl._family_name_order(cache, rec, melt, chars=chars,
                                   keys=cl.KIN_ORDER_PATERNAL)
        # a real flip vs the old default only when the paternal side alone said Western ('')
        if pa != "":
            continue
        new = cl.resolved_name_order(cache, int(cid), melt=melt, chars=chars)
        dn = cl.display_name(cache, int(cid), melt=melt, chars=chars)
        flipped.append((cid, rec.get("name_zh"), rec.get("name_full"),
                        rec.get("dynasty_name"), rec.get("house_name"),
                        pa, ho, new, dn))

    print(f"flipped count = {len(flipped)}")
    print(f"{'cid':>10} {'nz':<6} {'old name_full':<14} {'dyn':<8} "
          f"{'house':<10} {'pa':<4} {'house_ord':<20} {'new':<22} {'render'}")
    for row in flipped:
        cid, nz, nf, dyn, house, pa, mo, new, dn = row
        print(f"{cid:>10} {str(nz):<6} {str(nf):<14} {str(dyn):<8} "
              f"{str(house):<10} {str(pa):<4} {str(mo):<20} {str(new):<22} {dn}")


if __name__ == "__main__":
    main()
