# -*- coding: utf-8 -*-
"""v103 focused probe: verify issues 1 (hybrid-culture name), 2 (East-Asian name order),
6 (k_scotland cultural-name artifact) at the function level. Loads melt_1043 + the
player cache once. Read-only; asserts expected renderings."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
PID = 135480


def main():
    cache = json.load(open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8"))
    melt = cl.load_melt(os.path.join(DATA, "melt_1043_01_01.json.xz"))
    chars = cl.all_characters(melt)
    names = os.path.join(ROOT, "data", "names.json")
    facts = F.build_facts(cache, melt, names, as_of="1043.1.1", decade=None)
    f = facts["_facts"]

    print("==== Issue 2: East-Asian name order (display_name) ====")
    expect = {
        "143983": ("笛", "大江笛"),        # mother Japanese(119) -> Eastern
        "33666563": ("真一", "洪真一"),     # mother 陈婉贞 name_full Eastern -> Eastern
        "67133946": ("景思", "景思·洪"),    # own culture 82 (Catalan) -> Western, unchanged
        "135480": ("耀国", "耀国·洪堡"),    # own culture 271 -> Western, unchanged
        "67197928": ("都", "大江都"),       # own culture 119 -> Eastern, unchanged
        "16837136": ("婉贞", "陈婉贞"),     # culture None, house 保定陈
    }
    for cid, (nz, want) in expect.items():
        got = cl.display_name(cache, int(cid), melt=melt, chars=chars, date="1043.1.1")
        order = cl.resolved_name_order(cache, int(cid), melt=melt, chars=chars,
                                       date="1043.1.1")
        flag = "OK " if got == want else "XX "
        print(f"  {flag}{cid:>9} {nz}: got={got!r} want={want!r} order={order!r}")

    memo = {}
    for cid in ("143983", "33666563"):
        rec = (cache.get("characters") or {}).get(cid) or {}
        h = rec.get("dynasty_house")
        cl._house_name_order(cache, rec, melt, memo=memo)
        cv = (memo.get("__house_cul_order_idx__") or {}).get(h)
        fv = (memo.get("__house_order_idx__") or {}).get(h)
        print(f"  house {h} ({rec.get('house_name')}): culture_vote={cv} "
              f"name_full_vote={fv} order={cl._house_name_order(cache, rec, melt, memo=memo)!r}")

    print("==== Issue 1: hybrid-culture name ====")
    print("  _culture_name_of_id(271) =", repr(f._culture_name_of_id(271)))
    print("  _culture_name_of_id(82)  =", repr(f._culture_name_of_id(82)))
    print("  culture(135480, 1043.1.1)=", repr(f.culture(PID, "1043.1.1")))
    print("  culture(135480, 1015.1.1)=", repr(f.culture(PID, "1015.1.1")))
    print("  culture_history_lines(135480) =", f.culture_history_lines(PID))

    print("==== Issue 6: k_scotland (tid 445) ====")
    for d in ("1043.1.1", "900.1.1", "210.1.1"):
        print(f"  _name_at_date(445, {d}) = {f._name_at_date(445, d)!r}")
    print("  _title_name_at(445, 1043.1.1) =", repr(f._title_name_at(445, "1043.1.1")))


if __name__ == "__main__":
    main()
