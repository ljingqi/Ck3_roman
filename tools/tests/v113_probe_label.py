# -*- coding: utf-8 -*-
"""v113 probe (one melt load): the date behind the `邓公主李星雁` label, and the data volume a
Su-Xun-style HTML family tree would have to render.

Run:  $env:PYTHONIOENCODING='utf-8'; python -X utf8 tools/tests/v113_probe_label.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
PID = 207044
MELT = "melt_1155_01_01.json"

DATES = ["849.1.1", "867.1.1", "874.5.1", "879.1.1", "885.3.2", "886.1.1", "890.4.21",
         "897.6.6", "898.1.1", "904.11.30", "905.1.1", "952.1.29", "999.7.7", "1075.1.1",
         "1126.7.30", "1152.11.13"]


def find_by_name(cache, needle):
    out = []
    for cid, rec in (cache.get("characters") or {}).items():
        for k in ("name", "name_zh", "name_full"):
            v = rec.get(k)
            if isinstance(v, str) and needle in v:
                out.append((cid, k, v))
                break
    return out


def main():
    with open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8") as f:
        cache = json.load(f)
    names = os.path.join(DATA, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    print("载入熔件", MELT, flush=True)
    melt = cl.load_melt(os.path.join(DATA, MELT))
    facts = F.build_facts(cache, melt, names, as_of=None, decade=None, campaign=None)
    f = facts["_facts"]
    print("facts 建成; as_of =", f.as_of, "| cache characters =", len(cache.get("characters") or {}))

    for nm in ("李星雁", "李漼", "王蕡", "洪天姣"):
        hits = find_by_name(cache, nm)
        print(f"\n=== {nm}: {len(hits)} 命中")
        for cid, k, v in hits[:8]:
            print(f"   {cid} {k}={v}")

    # --- the h_china title: name history -------------------------------------
    print("\n=== h_china 头衔 ===")
    for tid, t in (f._lt or {}).items():
        if (t or {}).get("key") == "h_china":
            print("  tid", tid, "record keys:", list(t))
            print("  holder:", t.get("holder"), "capital:", t.get("capital"))
            print("  seq:", json.dumps(f._title_seqs.get(int(tid), [])[:60], ensure_ascii=False)[:2000])
            for d in DATES:
                try:
                    print(f"   {d}: name={f._name_at_date(int(tid), d)!r} "
                          f"src={f._name_source_key(int(tid), d)!r} "
                          f"gov={f._title_government(int(tid), d)!r} "
                          f"base={f.title_base_name(int(tid))!r} realm={f.realm_name(int(tid))!r}")
                except Exception as e:                       # noqa: BLE001
                    print(f"   {d}: ERR {e}")

    # --- labels of 李星雁 / 洪天姣 across dates ------------------------------
    print("\n=== labels ===")
    targets = {}
    for nm in ("李星雁", "洪天姣", "李漼"):
        hits = find_by_name(cache, nm)
        if hits:
            targets[nm] = int(hits[0][0])
    print("targets:", targets)
    for nm, cid in targets.items():
        rec = (cache.get("characters") or {}).get(str(cid)) or {}
        print(f"\n--- {nm} ({cid}) birth={rec.get('birth')} death={(rec.get('death') or {}).get('date')}")
        print("    family:", json.dumps(rec.get("family") or {}, ensure_ascii=False)[:400])
        for d in DATES:
            try:
                print(f"    {d}: {f.kin_label(cid, d)!r}")
            except Exception as e:                           # noqa: BLE001
                print(f"    {d}: ERR {e}")
        for p in F._asof_ids(f, (rec.get("family") or {}).get("father") or [], None) \
                if hasattr(F, "_asof_ids") else []:
            print("    father", p, "primary_at:", f._primary_title_at(int(p), as_of=None),
                  "former@1152:", f._former_high_title(int(p), "1152.11.13"))
        # raw style internals
        for d in ("885.3.2", "904.11.30", "1152.11.13"):
            try:
                print(f"    [{d}] _parent_prince_style={f._parent_prince_style(cid, d)!r} "
                      f"_emperor_sibling={f._emperor_sibling_style(cid, d)!r} "
                      f"tier/primary={f._primary_title_at(cid, as_of=d)}")
            except Exception as e:                           # noqa: BLE001
                print(f"    [{d}] ERR {e}")

    # --- tree volume ---------------------------------------------------------
    print("\n=== 世系/树 体量 ===")
    chain = [e for e in (cache.get("played_legacy") or [])
             if isinstance(e, dict) and isinstance(e.get("cid"), int)]
    print("played_legacy:", [(e.get("cid"), e.get("date"), e.get("name")) for e in chain])
    ids = set()
    for i, e in enumerate(chain):
        cid = int(e["cid"])
        rec = (cache.get("characters") or {}).get(str(cid)) or {}
        fam = rec.get("family") or {}
        date = F._gen_end_date(f, cid) or f.as_of
        kids = F._asof_ids(f, fam.get("child") or [], date)
        sibs = F._asof_ids(f, fam.get("siblings") or [], date)
        par = (F._asof_ids(f, fam.get("father") or [], date)
               + F._asof_ids(f, fam.get("mother") or [], date))
        ids.update(kids, sibs, par, [cid])
        print(f"  {cid} {f.name_or(cid)} date={date} kids={len(kids)} sibs={len(sibs)} "
              f"parents={len(par)}")
    print("union node count:", len(ids))
    houses = {}
    for cid in list(ids)[:4000]:
        rec = (cache.get("characters") or {}).get(str(cid)) or {}
        houses[rec.get("house")] = houses.get(rec.get("house"), 0) + 1
    print("houses among the union:", houses)


if __name__ == "__main__":
    main()
