# -*- coding: utf-8 -*-
"""v103 investigation probe for issues 3 (scripted-relation prefix) and 4 (桑莎 sibling+queen
contradiction). Loads the player cache once + melt_1043, dumps the facts I need. Read-only."""
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
    ch = cache.get("characters") or {}

    print("==== Issue 4: everyone named 桑莎 ====")
    pfam = (ch.get(str(PID)) or {}).get("family") or {}
    print("  protagonist family:")
    for k in ("primary_spouse", "spouse", "former_spouses", "concubine",
              "former_concubines", "siblings"):
        print(f"    {k:18}", pfam.get(k))
    for cid, rec in ch.items():
        if rec.get("name_zh") != "桑莎":
            continue
        print(f"\n  -- 桑莎 cid={cid} name_full={rec.get('name_full')!r} --")
        fam = rec.get("family") or {}
        for k in ("father", "mother", "primary_spouse", "spouse",
                  "former_spouses", "child", "siblings"):
            if fam.get(k):
                print(f"    {k:18}", fam.get(k))
        key = F.kin_key(cache, PID, int(cid),
                        spouse_back=f._spouse_back_index(), rev=f._kin_rev_index())
        print(f"    kin_key({PID},{cid}) = {key!r}  -> {F.kin_text(key)!r}")
        print(f"    blood_kin_word_for = {f.blood_kin_word_for(int(cid), PID)!r}")
        print(f"    kin_word_for       = {f.kin_word_for(int(cid), PID)!r}")
        print(f"    display_name       = {cl.display_name(cache, int(cid), melt=melt, chars=chars)!r}")
        print(f"    is PID in her spouse/former? spouse={PID in (fam.get('spouse') or [])} "
              f"former={PID in (fam.get('former_spouses') or [])} "
              f"primary={PID in (fam.get('primary_spouse') or [])}")

    print("\n==== Issue 3: relation_reasons / opinion kinds ====")
    rr = cache.get("relation_reasons") or {}
    print(f"  cache relation_reasons entries = {len(rr)}")
    kinds = {}
    for v in rr.values():
        if isinstance(v, dict) and v.get("kind"):
            kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
    print("  cached kind histogram:", dict(sorted(kinds.items(), key=lambda x: -x[1])))

    print("\n  melt _player_opinion_index (pairs touching PID):")
    pidx = f._player_opinion_index()
    print(f"    pairs = {len(pidx)}")
    mkinds = {}
    for (ow, tg), sr in pidx.items():
        for k in sr:
            mkinds[k] = mkinds.get(k, 0) + 1
    print("    melt kind histogram:", dict(sorted(mkinds.items(), key=lambda x: -x[1])))
    n = 0
    for (ow, tg), sr in pidx.items():
        nm = cl.display_name(cache, ow if tg == PID else tg, melt=melt, chars=chars)
        other = ow if tg == PID else tg
        direction = "PID->other" if ow == PID else "other->PID"
        print(f"    ({ow},{tg}) {direction} other={other} {nm!r} kinds={list(sr.keys())}")
        n += 1
        if n >= 25:
            break

    print("\n==== Issue 3: relation prefix (kin兼relation) ====")
    for cid in (33666563, 83966905, 67217991, 143983, 83959640):
        nm = cl.display_name(cache, cid, melt=melt, chars=chars)
        kin = f.kin_word_for(cid, PID)
        rel = f.relation_word_for(cid, PID)
        marked = F.KinScope(PID).mark(cid, nm, f)
        print(f"    cid={cid} {nm!r}: kin={kin!r} rel={rel!r} mark={marked!r}")


if __name__ == "__main__":
    main()
