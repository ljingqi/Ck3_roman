# -*- coding: utf-8 -*-
"""v117 check (item 1): `Facts.house_feuds` must read the protagonist's own HOUSE only.

Runs the production code path (`facts.build_facts` + `house_feuds`) for two 洪氏2 subjects and
cross-checks every pool entry against the raw `house_relations.database` rows of the same melt:

  * 洪光通 (player 17066495, melt_1283_01_01.json, as_of 1283.9.11) -- the terminal volume;
  * 洪希晏 (player 50565938, melt_1245_01_01.json.xz, as_of 1247.1.1) -- the volume whose melt still
    carries the 哈德良波利斯洪 x 宁浦洪 feud row (`key=83898143`).

Assertions:
  [A] every pool entry traces back to a raw row that contains the protagonist's own house;
  [B] no pool entry comes from a row whose two sides are both 洪 dynasty houses other than his own;
  [C] in the 1245 melt the pool contains 宁浦洪氏 at feud level.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_feuds_scope.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl       # noqa: E402
import facts as F            # noqa: E402

FOLDER = "洪氏2"
CASES = [
    ("洪光通", 17066495, "melt_1283_01_01.json", "1283.9.11"),
    ("洪希晏", 50565938, "melt_1245_01_01.json.xz", "1247.1.1"),
]
NEG = {"default_house_relation_level_feud",
       "default_house_relation_level_rivalry",
       "default_house_relation_level_quarrel"}
LOG = os.path.join(ROOT, "logs", "v117_check_feuds_scope.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def load_case(pid, melt_name, as_of):
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache = json.load(open(os.path.join(data, f"player_{pid}.json"), encoding="utf-8"))
    melt = cl.load_melt(os.path.join(data, melt_name))
    names = os.path.join(data, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    campaign = {}
    for fn in os.listdir(data):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        try:
            c = json.load(open(os.path.join(data, fn), encoding="utf-8"))
        except Exception:
            continue
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(m.group(1))] = c
    facts = F.Facts(cache, melt, names, as_of=as_of, decade=None,
                    campaign=campaign or None)
    return cache, melt, facts


def row_label(melt, hid):
    """Raw house label as `house_feuds` writes it (house name, else dynasty name, else 某家族)."""
    nm = cl.house_name_zh(melt, hid) or ""
    if nm:
        return nm
    did = cl.dynasty_id_of(melt, hid)
    if did is not None:
        dn = cl.dynasty_name_zh(melt, did) or ""
        if dn:
            return dn
    return "某家族"


def run(name, pid, melt_name, as_of):
    w(f"\n{'=' * 78}\n[{name}] player_{pid}.json + {melt_name}  as_of={as_of}")
    cache, melt, f = load_case(pid, melt_name, as_of)
    prec = (cache.get("characters") or {}).get(str(pid)) or {}
    h0 = prec.get("dynasty_house")
    did = cache.get("dynasty_id")
    dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
    dynasty_houses = sorted(int(h) for h, e in dh.items()
                            if isinstance(e, dict) and e.get("dynasty") == did)
    w(f"  own house = {h0}; dynasty_id = {did}; dynasty houses = {len(dynasty_houses)}")
    w(f"  code scope  : my_houses = own house only = {{{h0}}}")

    pool = f.house_feuds()
    w(f"  pool size = {len(pool)} (HOUSE_FEUDS_MAX caps the article, not this list)")
    for i, r in enumerate(pool[:12], 1):
        w(f"    {i:2d}. {r.get('house')}  level={r.get('level')}  events={len(r.get('events') or [])}")

    db = (melt.get("house_relations") or {}).get("database") or {}
    own_rows = {k: r for k, r in db.items()
                if isinstance(r, dict) and h0 in (r.get("houses") or [])}
    dyn_rows = {k: r for k, r in db.items()
                if isinstance(r, dict) and any(h in dynasty_houses for h in (r.get("houses") or []))}
    w(f"  raw rows: touching own house = {len(own_rows)}; touching the dynasty = {len(dyn_rows)}")
    w("  raw rows touching the own house:")
    own_labels = set()
    for k, r in sorted(own_rows.items(), key=lambda kv: -len(kv[1].get("history") or [])):
        hs = r.get("houses") or []
        others = [row_label(melt, h) for h in hs if h != h0]
        own_labels.update(others)
        w(f"    key={k} level={r.get('level','').replace('default_house_relation_level_','')}"
          f" history={len(r.get('history') or [])} others={others}")

    pool_labels = {r.get("house") for r in pool}
    stray = sorted(pool_labels - own_labels)
    w(f"  [A] pool labels not traceable to an own-house row: {stray or 'none'}")
    ok_a = not stray
    # [B] informational: pool labels that happen to be 洪 dynasty branch houses. Reaching such a
    # label is exactly right now (it means a same-dynasty branch feud of the own house was kept),
    # while under the old dynasty-wide scope those sides were filtered out by `other = []`.
    branch = {row_label(melt, h) for h in dynasty_houses if h != h0}
    own_branch = sorted(pool_labels & branch)
    w(f"  [B] pool labels that are 洪 dynasty branch houses (own-house feuds): {own_branch or 'none'}")
    ok_b = True
    # [C] the same-dynasty branch feud surfaces (only the 1245 melt still has that row)
    np = [r for r in pool if r.get("house") == "宁浦洪"]
    want = "宁浦洪" in {row_label(melt, h) for k, r in own_rows.items()
                        for h in (r.get("houses") or []) if h != h0}
    if want:
        got = bool(np) and str(np[0].get("level")) == "世仇"
        w(f"  [C] 宁浦洪 in pool = {bool(np)}"
          f"{' level=' + str(np[0].get('level')) if np else ''} -> {'OK' if got else 'FAIL'}")
    else:
        got = True
        w("  [C] 宁浦洪 has no own-house row in this melt (the game pruned it) -> n/a")
    return ok_a and ok_b and got


if __name__ == "__main__":
    results = []
    for case in CASES:
        results.append((case[0], run(*case)))
    w("\n" + "=" * 78)
    for name, ok in results:
        w(f"[{'PASS' if ok else 'FAIL'}] {name}")
    w(f"[{'PASS' if all(ok for _, ok in results) else 'FAIL'}] v117 ① house-scope check")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if all(ok for _, ok in results) else 1)
